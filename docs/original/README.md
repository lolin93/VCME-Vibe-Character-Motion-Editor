# VCME V58 本機展示版

新資料夾獨立於原始實驗專案。雙擊 `Start_Demo.cmd`，在瀏覽器開啟 http://127.0.0.1:7860。
需求：Windows Python 3.10+、Docker Desktop Linux engine；完整生成與 SAM2 使用 NVIDIA GPU。
所有權重實體放在本資料夾；Docker 執行環境備份在 `runtime/vcme-storymem.tar`，缺少映像時啟動器會匯入。

## 使用方式

首頁現在固定從空白開始，不會預載範例、過去上傳素材或上次選取的影片。點中央「上傳影片」或左側「＋ 匯入」開始；重新整理也會回到空白素材區。過往檔案與生成結果不會刪除，需要時可從「紀錄」主動查看。

1. 可直接播放 `assets/V58_Balanced.mp4`，它是歷史 V58 Balanced 成果的原樣副本。
2. 點「匯入」上傳自己的影片。原檔存在 `media/<ID>/original.upload`；另建 H.264、30 fps、最長邊 854 px 的工作副本，預覽、條件取樣、接回都使用同一份工作副本，不會偷偷換成範例。
3. 選開始／結束時間，也可拖動紫色時間軸把手；預設 3 秒，展示版目前允許 1–10 秒，首尾各保留至少 2 幀原片供接點診斷。上傳目前限制 100 MB、2–60 秒，控制解碼記憶體用量。
4. 在修改區間內暫停並點人物。SAM2 以該幀為條件雙向追蹤，綠色遮罩為真實結果，可拖動播放頭檢查。若不對，重新點選。修改影片或區間會使舊遮罩失效。
5. 輸入動作、按「生成新片段」。使用本地 StoryMem/Wan2.2 新生成，再套用可選 V57 背景修復與 V58 尾端調速。自訂提示不再套用歷史揮手專用的禁止跳舞等負面詞。
6. 完成後切換「生成結果」，正常速度／慢速查看，再點「匯出影片」。原始工作影片的音軌會保留至輸出（AAC），不是生成音訊。
7. 結果、seed、完整設定、記錄、C1/C2 評估存入 `jobs/<唯一ID>`。進階資訊可查看工作紀錄；過去的修復／調速工作與成果仍保留，但新版主要操作不再用它們代替上傳影片生成。

## 沿用配方與展示版調整

- StoryMem WanM2V/WanModel_Memory + Wan2.2-I2V-A14B + MI2V high/low LoRA。
- 16 fps、40 steps、seed 預設 2025、CFG 端點 2.75／中段 4.50。幀數依時長調整為 `4 * max(4, floor(duration * 4 + 0.5)) + 1`，3 秒仍為 49 幀，2.5 秒為 41 幀。條件取樣包含所選首尾時間，最終接回使用指定時長，不直接用模型檔案容器時長。
- SAM2 全時段人物 union，dilation 25、Gaussian sigma 4；首尾各一個 hard latent lock。
- 關閉 pose、soft lock、overlap、VACE、reference K/V、端點 flow/loss 等實驗選項。
- 實際原 runner 從 5 張候選關鍵幀選首／中／尾 3 張加入初始 memory bank，max memory capacity=5、fix=3；本版沿用此行為。五張候選不等於五張都輸入初始 memory。
- V57：原片／生成的人物遮罩聯集、local window 1、guard 18、feather 24、雙向 Farneback confidence floor 0.72。
- V58 Balanced：最後 15 個原時間軸幀、終點斜率 0.40、單調 cubic-Hermite 重採樣、inverse letterbox 接合。

## 邊界與來源

原生生成的配方以 V52 恢復的 V40 執行設定為依據；新影片、不同時長與通用動作提示是展示版新增適配，不可宣稱與歷史 V40/V58 逐像素相同。V58 外部後處理不創造新的語意動作，包含本次新生成幀的線性插值。完整新生成仍需人工檢查，尚未保證任意影片完全無痕或已證明跨場景泛化。模型畫布仍是 480×832，橫式影片以 letterbox 適配，人物過小或多人遮擋時可能失敗。較長片段尚未完整驗證，可能顯存不足。

沿用的核心引擎檔案含停用的相容分支；本展示沒有其他實驗入口、實驗權重、實驗結果目錄。保留這些相容函式是為避免改寫已驗證生成核心。`scripts/evaluate_optical_flow_epe.py` 是 V58 時間取樣工具的函式依賴；舊 2.05 門檻不作展示版通過條件。另輸出 C1/C2 僅供比較。

預訓練模型、SAM2 及上游程式不屬於本專案從零訓練成果；上游授權檔保留在 `external`。Docker archive 是既有相容執行環境，可能含歷史建置檔；應用透過新資料夾 `/workspace` 執行，不會執行映像中的舊腳本。

## 搬移、關閉與資料

可搬移整個資料夾。勿只搬移 app：models、external、scripts、src 與 assets 均為依賴。
啟動服務僅監聽 127.0.0.1，不對區域網路公開。一次只執行一項 GPU 工作。
請等工作完成後 Ctrl+C 停止網頁服務；關閉 UI 不會強制取消正在執行的 Docker 工作。
本版沒有修改原專案、重啟 WSL、停止其他容器或安裝 Windows 套件。

## 2026-09-15 UI 改版與回溯

新增 `app/editor.js`、`app/editor.css`、`app/editor_api.py`、`app/selection.py`；修改展示副本的 `app/server.py`、`app/pipeline.py`、`external/sam2/run_tracking.py`。StoryMem 核心、模型權重及歷史成果未改。舊版 UI／管線與 SAM2 runner 備份在 `runtime/ui_previous_20260915`。`COPY_VERIFICATION.json` 是打包當時的複製驗證，不代表此次主動修改的展示程式仍與原件相同。

驗證：`python app/test_editor.py`；瀏覽器測試 `app/check_editor.cjs`（需本地 Playwright 與 `runtime/upload_test_mirrored.mp4`）。UI 截圖在 `runtime/EDITOR_PREVIEW.png`，實測紀錄在 `runtime/EDITOR_TEST_REPORT.json`。鏡像測試片僅用於驗證上傳不混用來源，不是獨立跨場景品質資料集。
