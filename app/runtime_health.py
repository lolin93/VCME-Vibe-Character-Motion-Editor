"""Bounded, read-only checks of the existing compute environment."""
import subprocess

def health():
    try:
        p=subprocess.run(['docker','info','--format','{{.OSType}}'],capture_output=True,text=True,timeout=6)
        if p.returncode or p.stdout.strip()!='linux':
            return {'ready':False,'code':'engine_unavailable','message':'運算服務尚未就緒。請確認 Docker Desktop 顯示 Engine running，再按「重新檢查」。影片已保留，現在不需要重複點人物。','detail':(p.stderr or p.stdout)[-1500:]}
        return {'ready':True,'code':'ready','message':'運算服務已連線，可以選取人物。'}
    except (OSError,subprocess.TimeoutExpired) as exc:
        return {'ready':False,'code':'engine_unavailable','message':'無法連線到運算服務。請先開啟 Docker Desktop，等引擎啟動後按「重新檢查」。影片不會遺失。','detail':str(exc)}

def failure(log):
    if any(s in log.lower() for s in ['dockerdesktoplinuxengine','cannot connect to the docker','docker daemon','/_ping']):
        return '運算服務連線失敗，人物辨識尚未開始。請確認 Docker Desktop 引擎已啟動，再重新檢查。'
    if 'out of memory' in log.lower():
        return 'GPU 記憶體不足。請縮短修改區間後重試；原片已保留。'
    if 'did not find a usable object' in log:
        return '這個位置沒有辨識到可用人物。請點在人物軀幹內，或換到人物較清楚的一幀。'
    if 'not tracked at the first frame' in log:
        return '人物在修改區間起點沒有被追蹤到。請調整起點，讓人物在整段中可見，再重新選取。'
    return '這次處理未完成，原片已保留。請展開技術紀錄查看原因；不會使用舊影片替代結果。'

