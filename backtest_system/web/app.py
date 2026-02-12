from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import os

from backtest_system.core.config import load_config
from backtest_system.core.database import DatabaseAPI

app = FastAPI(title="回测系统", description="自动策略回测系统Web接口")

_CFG = load_config(os.getenv("BACKTEST_CONFIG"))
_DB = DatabaseAPI(_CFG.database.url, _CFG.api)

@app.get("/api/tasks")
def list_tasks(limit: int = 20):
    """获取任务列表"""
    if not _CFG.database.url:
        raise HTTPException(status_code=503, detail="BACKTEST_DB_URL is not configured")
    rows = _DB.read("SELECT * FROM backtest_tasks ORDER BY created_at DESC LIMIT %s", (limit,))
    return {"tasks": rows, "total": len(rows)}

@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """获取任务详情"""
    if not _CFG.database.url:
        raise HTTPException(status_code=503, detail="BACKTEST_DB_URL is not configured")
    rows = _DB.read("SELECT * FROM backtest_tasks WHERE task_id = %s LIMIT 1", (task_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Task not found")
    return rows[0]

@app.get("/api/tasks/{task_id}/logs")
def get_task_logs(task_id: str):
    """获取任务执行日志"""
    if not _CFG.database.url:
        raise HTTPException(status_code=503, detail="BACKTEST_DB_URL is not configured")
    rows = _DB.read("SELECT * FROM task_logs WHERE task_id = %s ORDER BY created_at ASC", (task_id,))
    return {"task_id": task_id, "logs": rows}

@app.get("/api/reports/{task_id}/download")
def download_report(task_id: str):
    """下载Excel报告"""
    path = os.path.join(_CFG.app.output_dir, f"{task_id}.xlsx")
    if os.path.exists(path):
        return FileResponse(path, filename=f"{task_id}.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    raise HTTPException(status_code=404, detail="Report not found")

@app.get("/api/health")
def health_check():
    """健康检查"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
