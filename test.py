import requests
import subprocess
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

def check_url(index, base_url, extension, headers, max_retries=3):
    """
    ฟังก์ชันสำหรับ Thread เพื่อเช็คว่า URL นี้มีอยู่จริงไหม (ทำงานแยกกันอิสระ)
    """
    url = f"{base_url}{index}{extension}"
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # ใช้ timeout สั้นๆ เพื่อความเร็วในการเช็คหลายๆ thread
            response = requests.head(url, headers=headers, timeout=5)
            return index, url, response.status_code
        except requests.exceptions.Timeout:
            retry_count += 1
            if retry_count < max_retries:
                print(f"⚠ Timeout on {index}, retrying ({retry_count}/{max_retries})...")
                time.sleep(1)  # รอก่อนลองใหม่
            else:
                print(f"✗ Timeout on {index} after {max_retries} retries")
                return index, url, 0
        except requests.RequestException as e:
            # ถ้า Error (เน็ตหลุด) ให้ถือว่าเป็น code 0
            return index, url, 0
    
    return index, url, 0

def download_video(url, output_path, headers, max_retries=5):
    """
    ดาวน์โหลดวิดีโอจาก URL ไปยังไฟล์ (มีการ retry)
    """
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True, output_path
            else:
                return False, None
        except requests.exceptions.Timeout:
            retry_count += 1
            if retry_count < max_retries:
                print(f"⚠ Download timeout for {os.path.basename(output_path)}, retrying ({retry_count}/{max_retries})...")
                time.sleep(2)  # รอนานขึ้นสำหรับการดาวน์โหลด
            else:
                print(f"✗ Download failed for {url} after {max_retries} retries")
                return False, None
        except requests.exceptions.ConnectionError as e:
            retry_count += 1
            if retry_count < max_retries:
                print(f"⚠ Connection error, retrying ({retry_count}/{max_retries})...")
                time.sleep(2)
            else:
                print(f"✗ Connection error downloading {url}: {e}")
                return False, None
        except requests.RequestException as e:
            print(f"Error downloading {url}: {e}")
            return False, None
    
    return False, None

def merge_videos_ffmpeg(video_list, output_file):
    """
    รวมวิดีโอหลายไฟล์เป็นไฟล์เดียวใช้ ffmpeg
    """
    if not video_list:
        print("No videos to merge")
        return False
    
    # สร้าง concat demuxer file
    concat_file = "concat_list.txt"
    try:
        with open(concat_file, 'w') as f:
            for video_path in video_list:
                f.write(f"file '{os.path.abspath(video_path)}'\n")
        
        print(f"Merging {len(video_list)} videos...")
        cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file,
            '-c', 'copy',
            '-y',
            output_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✓ Successfully merged to {output_file}")
            return True
        else:
            print(f"Error merging videos: {result.stderr}")
            return False
    except Exception as e:
        print(f"Exception during merge: {e}")
        return False
    finally:
        if os.path.exists(concat_file):
            os.remove(concat_file)

def play_video_mpv(video_path):
    """
    เล่นวิดีโอด้วย mpv
    """
    try:
        cmd = [
            'mpv',
            video_path,
            '--cache=yes',
            '--demuxer-max-bytes=128MiB',
            '--demuxer-readahead-secs=20'
        ]
        subprocess.run(cmd)
    except FileNotFoundError:
        print("Error: mpv not found")
    except Exception as e:
        print(f"Error playing video: {e}")

def stream_to_mpv_multithread():
    # --- ตั้งค่า Config ---
    base_url = "https://yuzu16.top/v1/segment/ff0b0f560dbf59361f995b80bd725ac0/1080p/1080p"
    extension = ".webp"
    
    start_index = 0
    batch_size = 256  # จำนวน Thread ที่จะรันพร้อมกัน (ตามที่ขอ)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    print(f"กำลังเริ่มโปรแกรม... (Threads: {batch_size})")

    # สร้างโฟลเดอร์สำหรับเก็บวิดีโอ
    download_dir = "downloaded_videos"
    Path(download_dir).mkdir(exist_ok=True)

    print("เริ่มยิงเช็ค URL และดาวน์โหลด...")

    current_batch_start = start_index
    is_running = True
    downloaded_videos = []
    found_404 = False

    while is_running and not found_404:
        # สร้าง Executor สำหรับ 28 threads
        results = []
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            # สั่งงาน 28 tasks พร้อมกัน (เช่น 0-27, รอบต่อไป 28-55)
            futures = {
                executor.submit(check_url, i, base_url, extension, headers): i 
                for i in range(current_batch_start, current_batch_start + batch_size)
            }
            
            # รอให้ทุก Thread ในชุดนี้ทำงานเสร็จ (หรือ Timeout)
            for future in as_completed(futures):
                results.append(future.result())

        # *** สำคัญมาก ***
        # เราต้องเรียงลำดับผลลัพธ์ตาม Index (0, 1, 2...) ก่อนส่งให้ MPV
        # เพราะ Thread อาจจะเสร็จไม่พร้อมกัน (เช่น 5 เสร็จก่อน 1) แต่ MPV ต้องเล่นเรียงลำดับ
        results.sort(key=lambda x: x[0])

        # วนลูปส่งผลลัพธ์ที่เรียงแล้ว และดาวน์โหลดวิดีโอ
        download_futures = {}
        with ThreadPoolExecutor(max_workers=batch_size) as dl_executor:
            for index, url, status in results:
                if status == 200:
                    output_path = os.path.join(download_dir, f"segment_{index:06d}{extension}")
                    future = dl_executor.submit(download_video, url, output_path, headers)
                    download_futures[future] = (index, output_path)
                elif status == 404:
                    print(f"\n>>> พบจุดสิ้นสุดที่หมายเลข {index} (404 Not Found)")
                    found_404 = True
                    break
                else:
                    print(f"Warning: หมายเลข {index} มีปัญหา (Status: {status})")
            
            # รอให้ดาวน์โหลดเสร็จ
            for future in as_completed(download_futures):
                success, output_path = future.result()
                index, path = download_futures[future]
                if success:
                    downloaded_videos.append((index, output_path))  # เก็บ index เพื่อการ sorting
                    print(f"✓ Downloaded segment {index}")
                else:
                    print(f"✗ Failed to download segment {index}")

        if found_404:
            break

        # ขยับไป Batch ถัดไป
        current_batch_start += batch_size
        print(f"Processed batch up to {current_batch_start - 1}...", end='\r')

    print(f"\n\n✓ Downloaded {len(downloaded_videos)} segments total")
    
    # เรียงลำดับไฟล์ที่ดาวน์โหลดตามเลข index (ไม่ใช่ชื่อไฟล์)
    downloaded_videos.sort(key=lambda x: x[0])
    
    # แยกเฉพาะ path สำหรับการ merge
    video_paths = [path for _, path in downloaded_videos]
    
    if video_paths:
        print(f"\nOrdering {len(video_paths)} videos before merge...")
        # รวมวิดีโอใช้ ffmpeg
        output_video = "merged_output.mp4"
        if merge_videos_ffmpeg(video_paths, output_video):
            print(f"\n✓ Starting playback with mpv...")
            play_video_mpv(output_video)
        else:
            print("Failed to merge videos")
    else:
        print("No videos were downloaded")

if __name__ == "__main__":
    stream_to_mpv_multithread()