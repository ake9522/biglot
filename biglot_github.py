import os
import time
import shutil
import subprocess
import pandas as pd
from io import StringIO
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from lxml import html as lxml_html
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# CONFIGURATION
# ==========================================
HEADLESS_MODE = True  # แนะนำให้เป็น True สำหรับ GitHub Actions
WAIT_TIMEOUT = 20     # เวลาสูงสุดที่จะรอ Element (วินาที)

# Path Configuration (ปรับให้รองรับการรันบน GitHub / Local)
LOCAL_PATH = "./"
LOCAL_PATH_DATA = os.path.join(LOCAL_PATH, "data_biglot/")

# XPATH Mappings ที่รวมทั้ง Date และ Big Lot เข้าด้วยกัน
XPATH_MAPPINGS = {
    "Date": '//div[@class="site-container page-body mt-5"]//div[@class="d-flex align-items-center mb-3"]',
    "Big Lot": '//div[@class="site-container page-body mt-5"]//div[@class="table-biglot shadow-none border-0 mb-4"]'
}

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def kill_chrome_instances():
    """สั่งฆ่า Process Chrome และ Driver ที่ค้างอยู่ในระบบ (ป้องกัน Port ชนกันบน GitHub Runner)"""
    try:
        subprocess.run(["pkill", "-f", "chrome"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "chromedriver"], stderr=subprocess.DEVNULL)
    except:
        pass

def create_driver():
    """สร้าง WebDriver สำหรับรันบน GitHub Actions หรือ Local ได้อย่างเสถียร"""
    options = webdriver.ChromeOptions()
    if HEADLESS_MODE:
        options.add_argument("--headless=new")
    
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument('--ignore-certificate-errors')
    options.add_argument("--window-size=1920,1080")

    max_init_retries = 3
    for i in range(max_init_retries):
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(45)
            return driver
        except Exception as e:
            print(f"⚠️ Attempt {i+1}: Failed to start Chrome. Retrying in 5s... ({e})")
            time.sleep(5)
    
    raise Exception("🔥 Failed to initialize Chrome after multiple retries.")

def setup_environment():
    """เตรียม Folder และเคลียร์ไฟล์เก่าทิ้งก่อนเริ่มรันใหม่ทุกครั้ง"""
    print("🔧 กำลังเตรียม Environment...")
    if os.path.exists(LOCAL_PATH_DATA):
        shutil.rmtree(LOCAL_PATH_DATA)
        print(f"🗑️ ลบโฟลเดอร์เก่า: {LOCAL_PATH_DATA}")
    
    os.makedirs(LOCAL_PATH_DATA, exist_ok=True)
    print(f"✅ สร้างโฟลเดอร์ใหม่: {LOCAL_PATH_DATA}")

def parse_page_content(html_content, page_url):
    """
    แกะข้อมูลจาก HTML โดยแยกจัดการตาม XPath แต่ละตัว:
    - Date: จัดการเก็บเป็นข้อความทั่วไป (Text)
    - Big Lot: จัดการแปลงตาราง HTML เป็น Rows / Columns
    """
    tree = lxml_html.fromstring(html_content)
    extracted_data = []

    for label, xpath in XPATH_MAPPINGS.items():
        try:
            elements = tree.xpath(xpath)
            for el in elements:
                el_html = lxml_html.tostring(el, encoding='unicode')
                
                # หากเป็น Big Lot และมีตารางภายใน
                if label == "Big Lot" and "<table" in el_html.lower():
                    try:
                        tables = pd.read_html(StringIO(el_html))
                        for df in tables:
                            if isinstance(df.columns, pd.MultiIndex):
                                df.columns = [' | '.join([str(c) for c in col if c]) for col in df.columns]
                            else:
                                df.columns = df.columns.astype(str)

                            # บันทึก Header ของตาราง
                            header_row = [label, page_url] + df.columns.tolist()
                            extracted_data.append(header_row)

                            # บันทึกแถวข้อมูลในตาราง
                            for row in df.itertuples(index=False, name=None):
                                extracted_data.append([label, page_url] + list(row))
                    except Exception as e:
                        print(f"⚠️ Table parse error for {label}: {e}")
                else:
                    # สำหรับ Date หรือส่วนที่ไม่ใช่ตาราง (เก็บเป็น Text)
                    text = el.text_content().strip()
                    if text:
                        extracted_data.append([label, page_url, text])
        except Exception as e:
            print(f"⚠️ XPath error for {label}: {e}")

    return extracted_data

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    start_time = time.time()

    # 1. ล้าง Process ค้างและเตรียมโฟลเดอร์ใหม่
    kill_chrome_instances()
    setup_environment()

    driver = None
    try:
        print("🔧 กำลังสร้าง WebDriver...")
        driver = create_driver()

        url = "https://www.settrade.com/th/equities/market-data/biglot"
        print(f"🌐 กำลังเปิดเว็บ: {url}")
        driver.get(url)

        # Smart Wait: รอให้โครงสร้างหลักโหลดเสร็จ
        print("⏳ กำลังรอ Element โหลด...")
        WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.presence_of_element_located((By.CLASS_NAME, "site-container"))
        )

        # หน่วงเวลาให้ JavaScript เติมข้อมูลลงในตารางและคอมโพเนนต์จนครบ
        print("⏳ กำลังรอข้อมูล JavaScript แสดงผลครบถ้วน...")
        time.sleep(6)

        # ดึง Page Source
        html_source = driver.page_source

        # ประมวลผลข้อมูล
        data = parse_page_content(html_source, url)

        # บันทึกผลลัพธ์ลง CSV
        if data:
            max_cols = max(len(r) for r in data)
            cols = ["TableName", "URL"] + [f"Column{i+1}" for i in range(max_cols - 2)]
            df_out = pd.DataFrame(data, columns=cols)

            csv_path = os.path.join(LOCAL_PATH_DATA, "biglot_market_data.csv")
            df_out.to_csv(csv_path, index=False, encoding="utf-8-sig")
            print(f"💾 บันทึกไฟล์สำเร็จ: {csv_path} ({len(df_out)} แถว)")
        else:
            print("⚠️ ไม่มีข้อมูลถูกดึงออกมาจาก XPath ที่กำหนด")

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดระหว่างรันสคริปต์: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
            print("🔒 ปิดการทำงาน WebDriver เรียบร้อย")

    total_time = time.time() - start_time
    print(f"\n✨ เสร็จสิ้นกระบวนการทั้งหมดในเวลา: {total_time/60:.2f} นาที ✨")

if __name__ == "__main__":
    main()