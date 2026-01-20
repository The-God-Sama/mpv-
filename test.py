import requests
import subprocess
import time
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --- ตั้งค่า Config ---
BASE_URL = "..."
EXTENSION = ".webp" 
BATCH_SIZE = 50       # จำนวน Thread ที่เช็ค/โหลดพร้อมกัน (แนะนำ 20-50 เพื่อไม่ให้ Server บล็อค)
DOWNLOAD_DIR = "downloaded_videos"
OUTPUT_FILENAME = "final_movie.mp4"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def check_url(index):
    """เช็คว่า URL มีอยู่จริงหรือไม่ (HEAD Request)"""
    url = f"{BASE_URL}{index}{EXTENSION}"
    try:
        response = requests.head(url, headers=HEADERS, timeout=5)
        return index, url, response.status_code
    except:
        return index, url, 0

def download_video(index, url, output_path):
    """ดาวน์โหลดไฟล์ (ถ้ามีไฟล์แล้วฟังก์ชันนี้จะไม่ถูกเรียก หรือถูกดักไว้ก่อน)"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return index, output_path, True
    except Exception as e:
        print(f"Error downloading {index}: {e}")
    return index, output_path, False

def merge_videos_ffmpeg(video_list, output_file):
    """รวมไฟล์วิดีโอด้วย FFmpeg"""
    if not video_list:
        return False
    
    # สร้างไฟล์รายการชื่อไฟล์สำหรับ FFmpeg (absolute path)
    concat_file = "concat_list.txt"
    with open(concat_file, 'w', encoding='utf-8') as f:
        for path in video_list:
            # ต้องแปลง path เป็น absolute และ escape backslash สำหรับ Windows
            abs_path = os.path.abspath(path).replace('\\', '/')
            f.write(f"file '{abs_path}'\n")
    
    print(f"\n[Merge] กำลังรวม {len(video_list)} ไฟล์เป็น {output_file}...")
    
    cmd = [
        'ffmpeg', '-f', 'concat', '-safe', '0',
        '-i', concat_file, '-c', 'copy', '-y', output_file
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[Merge] สำเร็จ! ไฟล์อยู่ที่: {output_file}")
        os.remove(concat_file) # ลบไฟล์ list ทิ้งเมื่อเสร็จ
        return True
    except subprocess.CalledProcessError:
        print("[Merge] เกิดข้อผิดพลาดในการรวมไฟล์ (เช็คว่าลง FFmpeg หรือยัง)")
        return False

def main():
    # สร้างโฟลเดอร์เก็บไฟล์
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    print(f"--- เริ่มต้นการทำงาน (Threads: {BATCH_SIZE}) ---")
    
    all_valid_segments = [] # เก็บ tuple (index, path)
    current_index = 0
    is_running = True

    while is_running:
        print(f"\nกำลังตรวจสอบ Batch ที่ {current_index} ถึง {current_index + BATCH_SIZE - 1}...")
        
        # 1. เช็ค URL ก่อนว่ามีอยู่จริงไหม (Parallel Check)
        check_futures = []
        valid_urls_in_batch = [] # เก็บ (index, url) ที่มีอยู่จริง
        
        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            for i in range(current_index, current_index + BATCH_SIZE):
                check_futures.append(executor.submit(check_url, i))
            
            for future in as_completed(check_futures):
                idx, url, status = future.result()
                if status == 200:
                    valid_urls_in_batch.append((idx, url))
                elif status == 404:
                    print(f"!!! เจอจุดสิ้นสุดที่หมายเลข {idx} (404 Not Found) !!!")
                    is_running = False # สั่งหยุด Loop ใหญ่

        # ถ้าไม่มี URL ที่ใช้ได้เลยใน Batch นี้ แสดงว่าจบแล้วหรือ Error
        if not valid_urls_in_batch:
            if is_running: 
                print("ไม่พบไฟล์ใน Batch นี้เลย (อาจจะจบแล้ว)")
                break

        # 2. คัดกรอง: อันไหนมีไฟล์แล้วข้าม อันไหนไม่มีให้โหลด
        download_tasks = []
        batch_results = [] # เก็บผลลัพธ์ของ batch นี้

        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as dl_executor:
            for idx, url in valid_urls_in_batch:
                filename = f"segment_{idx:06d}{EXTENSION}" # ตั้งชื่อไฟล์แบบมีเลขนำหน้า 000001
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                
                # --- ลอจิกเช็คไฟล์ซ้ำ ---
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    # ถ้ามีไฟล์แล้ว ข้ามเลย
                    print(f"• [ข้าม] มีไฟล์แล้ว: {idx}", end='\r')
                    batch_results.append((idx, filepath))
                else:
                    # ถ้ายังไม่มี สั่งโหลด
                    # print(f"-> [โหลด] กำลังเพิ่มคิว: {idx}")
                    download_tasks.append(dl_executor.submit(download_video, idx, url, filepath))

            # รอให้โหลดเสร็จ
            if download_tasks:
                print(f"\nกำลังดาวน์โหลด {len(download_tasks)} ไฟล์ใหม่...")
                for future in as_completed(download_tasks):
                    d_idx, d_path, success = future.result()
                    if success:
                        print(f"✓ [เสร็จ] {d_idx}", end=' ')
                        batch_results.append((d_idx, d_path))
                    else:
                        print(f"✗ [พลาด] {d_idx}")
            else:
                print("\nไฟล์ครบหมดแล้วใน Batch นี้ ไม่ต้องโหลดเพิ่ม")

        # เพิ่มผลลัพธ์ของ Batch นี้ลงกองกลาง
        all_valid_segments.extend(batch_results)
        
        # ขยับ Index ไป Batch ถัดไป
        current_index += BATCH_SIZE

    # --- จบ Loop การโหลด ---
    
    if all_valid_segments:
        # 3. เรียงลำดับไฟล์ตาม Index (สำคัญมาก ไม่งั้นวิดีโอสลับไปมา)
        print("\n\nกำลังเรียงลำดับไฟล์...")
        all_valid_segments.sort(key=lambda x: x[0])
        
        # ดึงมาแค่ Path เพื่อส่งให้ FFmpeg
        final_paths = [path for _, path in all_valid_segments]
        
        # 4. รวมไฟล์
        if merge_videos_ffmpeg(final_paths, OUTPUT_FILENAME):
            # 5. เล่นไฟล์
            print(f"กำลังเปิดไฟล์ {OUTPUT_FILENAME} ด้วย MPV...")
            try:
                subprocess.run(['mpv', OUTPUT_FILENAME])
            except FileNotFoundError:
                print("ไม่เจอโปรแกรม mpv ในเครื่อง (แต่ไฟล์รวมเสร็จแล้วนะ)")
    else:
        print("ไม่พบข้อมูลวิดีโอใดๆ")

if __name__ == "__main__":
    main()