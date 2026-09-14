import asyncio
import os
import random
import pandas as pd
import io
import streamlit as st
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ============================================================
# CẤU HÌNH GIAO DIỆN STREAMLIT
# ============================================================
st.set_page_config(
    page_title="Công cụ Cào Dữ Liệu Mã Số Thuế",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Công cụ Cào Dữ Liệu Mã Số Thuế (Masothue)")
st.markdown("Nhập liên kết danh sách và chọn số lượng trang bạn muốn lấy dữ liệu. Hệ thống sẽ tự động lọc các doanh nghiệp **có Số Điện Thoại**.")

# ============================================================
# HÀM BÓC TÁCH DỮ LIỆU
# ============================================================
def clean_text(text):
    if not text:
        return ""
    return " ".join(text.strip().split())

def parse_taxinfo_table(html_content, url):
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table", class_="table-taxinfo")
    
    if not table:
        return None

    data = {
        "Tên công ty": "",
        "Mã số thuế": "",
        "Điện thoại": "",
        "Địa chỉ Thuế": "",
        "Địa chỉ": "",
        "Tình trạng": "",
        "Tên quốc tế": "",
        "Tên viết tắt": "",
        "Người đại diện": "",
        "Ngày hoạt động": "",
        "Quản lý bởi": "",
        "Loại hình DN": "",
        "Ngành nghề chính": "",
        "URL": url
    }

    th_name = table.find("th", {"itemprop": "name"})
    if th_name:
        data["Tên công ty"] = clean_text(th_name.get_text())

    rows = table.find_all("tr")
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 2:
            continue

        label_td, val_td = tds[0], tds[1]
        for elem in val_td.find_all(["button", "script", "style", "svg", "i"]):
            elem.decompose()
            
        label = clean_text(label_td.get_text()).lower()
        val = clean_text(val_td.get_text())

        if "mã số thuế" in label:
            data["Mã số thuế"] = val
        elif "điện thoại" in label:
            data["Điện thoại"] = val
        elif "địa chỉ thuế" in label:
            data["Địa chỉ Thuế"] = val
        elif "địa chỉ" in label and not data["Địa chỉ"]:
            data["Địa chỉ"] = val
        elif "tình trạng" in label:
            data["Tình trạng"] = val
        elif "tên quốc tế" in label:
            data["Tên quốc tế"] = val
        elif "tên viết tắt" in label:
            data["Tên viết tắt"] = val
        elif "người đại diện" in label:
            data["Người đại diện"] = val
        elif "ngày hoạt động" in label:
            data["Ngày hoạt động"] = val
        elif "quản lý bởi" in label:
            data["Quản lý bởi"] = val
        elif "loại hình dn" in label:
            data["Loại hình DN"] = val
        elif "ngành nghề chính" in label:
            data["Ngành nghề chính"] = val

    return data

async def process_detail_url(context, detail_url):
    page = await context.new_page()
    try:
        await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,css}", lambda route: route.abort())
        await page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)
        
        try:
            await page.wait_for_selector("table.table-taxinfo", timeout=8000)
        except Exception:
            return None

        table_element = page.locator("table.table-taxinfo")
        if await table_element.count() > 0:
            html = await table_element.first.evaluate("el => el.outerHTML")
            return parse_taxinfo_table(html, detail_url)
        return None
    except Exception:
        return None
    finally:
        await page.close()

# ============================================================
# LUỒNG CHẠY CHÍNH (ASYNC)
# ============================================================
async def run_crawler(base_url, max_pages, status_box, progress_bar, table_placeholder):
    results = []
    processed_urls = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--js-flags=--max-old-space-size=512"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        for page_num in range(1, max_pages + 1):
            if "?" in base_url:
                page_url = f"{base_url}&page={page_num}" if page_num > 1 else base_url
            else:
                page_url = f"{base_url}?page={page_num}" if page_num > 1 else base_url

            status_box.info(f"📑 [Trang {page_num}/{max_pages}] Đang lấy danh sách từ: {page_url}")
            progress_bar.progress(page_num / max_pages)

            list_page = await context.new_page()
            try:
                await list_page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,css}", lambda route: route.abort())
                await list_page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(1)

                elements = await list_page.locator("div[data-prefetch]").all()
                urls_on_page = []
                
                for elem in elements:
                    prefetch_path = await elem.get_attribute("data-prefetch")
                    if prefetch_path:
                        full_url = prefetch_path if prefetch_path.startswith("http") else f"https://masothue.com{prefetch_path}"
                        if full_url not in processed_urls:
                            urls_on_page.append(full_url)

                urls_on_page = list(dict.fromkeys(urls_on_page))
                await list_page.close()

                # Cào chi tiết từng URL
                for idx, detail_url in enumerate(urls_on_page, 1):
                    status_box.info(f"📑 Trang {page_num}/{max_pages} | 🎯 Chi tiết ({idx}/{len(urls_on_page)}): {detail_url}")
                    item = await process_detail_url(context, detail_url)
                    processed_urls.add(detail_url)

                    if item and item.get("Mã số thuế") and item.get("Điện thoại"):
                        results.append(item)
                        # Bảng cập nhật thời gian thực trên giao diện
                        df_temp = pd.DataFrame(results)
                        table_placeholder.dataframe(df_temp, use_container_width=True)
                    
                    await asyncio.sleep(random.uniform(1.0, 2.0))

            except Exception as e:
                status_box.warning(f"⚠️ Lỗi khi cào trang {page_url}: {e}")
                if not list_page.is_closed():
                    await list_page.close()

        await browser.close()
    return results

# ============================================================
# GIAO DIỆN NGƯỜI DÙNG (FORM NHẬP & NÚT BẮT ĐẦU)
# ============================================================
with st.form("crawler_form"):
    url_input = st.text_input(
        "Nhập Link danh sách cần cào:",
        value="https://masothue.com/tra-cuu-ma-so-thue-theo-loai-hinh-doanh-nghiep/ho-kinh-doanh-ca-the-20"
    )
    max_pages_input = st.number_input("Số trang muốn cào:", min_value=1, max_value=500, value=2, step=1)
    submit_button = st.form_submit_button("🚀 Bắt đầu cào dữ liệu")

if submit_button:
    if not url_input.strip():
        st.error("Vui lòng nhập URL hợp lệ!")
    else:
        status_box = st.empty()
        progress_bar = st.progress(0.0)
        table_placeholder = st.empty()

        with st.spinner("Hệ thống đang chạy Playwright..."):
            data = asyncio.run(run_crawler(
                url_input.strip(),
                int(max_pages_input),
                status_box,
                progress_bar,
                table_placeholder
            ))

        if data:
            status_box.success(f"🎉 Hoàn tất! Đã thu thập được {len(data)} doanh nghiệp có SĐT.")
            df_final = pd.DataFrame(data).drop_duplicates(subset=["Mã số thuế"], keep="first")
            
            # Xuất dữ liệu ra file Excel dạng Byte stream
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_final.to_excel(writer, index=False, sheet_name="MasoThue")
            excel_data = output.getvalue()

            # Nút Tải về file Excel
            st.download_button(
                label="📥 Tải file Excel kết quả",
                data=excel_data,
                file_name="danh_sach_masothue_sdt.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            status_box.warning("❌ Không tìm thấy thông tin công ty nào có số điện thoại.")