# 台股關注熱度掃榜

本機小工具：針對固定關注清單，手動更新並比較 **Google Trends 搜尋熱度** 與 **PTT Stock 討論熱度**，支援晨檢掃榜、單檔深挖與歷史曲線。

## 功能

- 晨檢掃榜：30 檔總表、排序、較上次變化
- 單檔深挖：Trends / PTT / 綜合歷史曲線、PTT 近文連結
- 搜尋：名稱、代號、別名、模糊比對（如 `國巨`、`2327`、`臻鼎`）
- 更新方式：**僅手動更新**
- 資料：本機 SQLite（`data/app.db`）

## 環境需求

- Python 3.10+
- 可連外網（Google Trends、PTT）

## 安裝與啟動

```bash
cd stock-heat-tracker
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

瀏覽器開啟終端機提示的本機網址即可。

## 使用方式

1. 進「晨檢掃榜」檢視清單  
2. 按「立即更新全部」或「更新目前篩選」手動抓取  
3. 點表格列，或切到「單檔深挖」看曲線與 PTT 近文  

可分別勾選是否更新 Trends / PTT。

## 熱度說明

| 指標 | 來源 | 說明 |
|------|------|------|
| Trends | Google Trends（TW） | 以標的名稱與代號查詢，取較高相對熱度（0–100） |
| PTT | PTT `Stock` 板 | 以名稱/代號/別名比對文章，綜合篇數與推文映射到 0–100；官方站不可用時自動改抓 pttweb.cc |
| 綜合 | 計算值 | `0.5 * Trends + 0.5 * PTT`（缺一側時用另一側） |

歷史曲線來自每次手動更新寫入的快照；首次使用需先更新才會有資料。

## 標的清單

清單位於 `data/stocks.json`，可自行增修 `aliases`。

## 測試

```bash
cd stock-heat-tracker
pytest -q
```

## 注意事項

- Google Trends 有頻率限制（易 429）。批量更新時會自動放慢；若仍失敗可稍後重試，或先只更新 PTT。失敗不會覆蓋舊分數。
- PTT 官方站若回傳錯誤，會自動改用 pttweb.cc 的 Stock 搜尋／最新頁。
- 本工具僅供關注熱度參考，**非投資建議**。
