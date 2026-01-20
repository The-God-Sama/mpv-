import requests
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

def check_url(index, base_url, extension, headers):
    """
    ฟังก์ชันสำหรับ Thread เพื่อเช็คว่า URL นี้มีอยู่จริงไหม (ทำงานแยกกันอิสระ)
    """
    url = f"{base_url}{index}{extension}"
    try:
        # ใช้ timeout สั้นๆ เพื่อความเร็วในการเช็คหลายๆ thread
        response = requests.head(url, headers=headers, timeout=5)
        return index, url, response.status_code
    except requests.RequestException:
        # ถ้า Error (เน็ตหลุด/Timeout) ให้ถือว่าเป็น code 0 หรือจัดการตามเหมาะสม
        return index, url, 0

def stream_to_mpv_multithread():
    # --- ตั้งค่า Config ---
    base_url = "https://yuzu16.top/v1/segment/ff0b0f560dbf59361f995b80bd725ac0/1080p/1080p"
    extension = ".webp"
    
    start_index = 0
    batch_size = 28  # จำนวน Thread ที่จะรันพร้อมกัน (ตามที่ขอ)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    print(f"กำลังเริ่มโปรแกรม... (Threads: {batch_size})")

    # --- เปิด MPV พร้อมตั้งค่า Cache (Preload) ---
    # --cache=yes : เปิดใช้งาน cache
    # --demuxer-max-bytes=128MiB : จอง RAM ไว้โหลดล่วงหน้าเยอะๆ (ลดกระตุก)
    # --demuxer-readahead-secs=20 : พยายามอ่านล่วงหน้า 20 วินาที
    cmd = [
        'mpv', 
        '--playlist=-', 
        '--cache=yes',
        '--demuxer-max-bytes=128MiB', 
        '--demuxer-readahead-secs=20'
    ]

    try:
        mpv_process = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.DEVNULL, # ปิด Output รกๆ
            stderr=subprocess.DEVNULL, 
            text=True, 
            bufsize=0
        )
    except FileNotFoundError:
        print("Error: ไม่พบ mpv")
        return

    print("เริ่มยิงเช็ค URL และ Preload เข้า MPV...")

    current_batch_start = start_index
    is_running = True

    while is_running:
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

        # วนลูปส่งผลลัพธ์ที่เรียงแล้วเข้า MPV
        for index, url, status in results:
            if status == 200:
                # ส่ง URL เข้า MPV
                try:
                    mpv_process.stdin.write(url + "\n")
                    # print(f"Added: {index}") # ปิดไว้จะได้ไม่ลายตา
                except BrokenPipeError:
                    print("MPV ถูกปิดไปแล้ว")
                    is_running = False
                    break
            elif status == 404:
                print(f"\n>>> พบจุดสิ้นสุดที่หมายเลข {index} (404 Not Found)")
                is_running = False
                break
            else:
                print(f"Warning: หมายเลข {index} มีปัญหา (Status: {status})")
                # คุณอาจจะเลือก break หรือข้ามก็ได้ ขึ้นอยู่กับความซีเรียสของข้อมูล
                # ในที่นี้ถ้าไม่ใช่ 200 หรือ 404 เราจะข้ามไปก่อน

        # ตรวจสอบสถานะ MPV ว่ายังเปิดอยู่ไหม
        if mpv_process.poll() is not None:
            print("MPV Player Closed.")
            break

        # ขยับไป Batch ถัดไป
        current_batch_start += batch_size
        print(f"Processed batch up to {current_batch_start - 1}...", end='\r')

    # รอจบงาน
    if mpv_process.poll() is None:
        print("\nส่งข้อมูลครบแล้ว... รอ MPV เล่นจนจบ")
        mpv_process.stdin.close()
        mpv_process.wait()

if __name__ == "__main__":
    stream_to_mpv_multithread()