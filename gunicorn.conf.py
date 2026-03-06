# gunicorn.conf.py

import multiprocessing

# --- 服务器绑定 ---
# 绑定地址和端口，0.0.0.0 允许外部访问
bind = "127.0.0.1:8000"

# --- 工作进程 ---
# 建议设置：(CPU 核心数 * 2) + 1
# 如果是容器环境，建议通过环境变量传入，或者使用下面的动态计算
workers = multiprocessing.cpu_count() * 2 + 1
# 如果是在 Docker/K8s 中，通常固定为 1 或 2，由副本数控制并发
# workers = int(os.getenv("GUNICORN_WORKERS", "2"))

# 每个工作进程的线程数 (UvicornWorker 通常不需要多线程，保持默认 1 即可)
threads = 1

# --- 工作类 (关键) ---
# FastAPI 是 ASGI 应用，必须指定 uvicorn.workers.UvicornWorker
worker_class = "uvicorn.workers.UvicornWorker"

# --- 超时设置 ---
# 请求超时时间 (秒)，长任务需要调大
timeout = 30

# 优雅重启超时时间 (秒)，给进程处理完当前请求的时间
graceful_timeout = 30

# 保持连接超时时间
keepalive = 5

# --- 日志配置 ---
# 访问日志路径，'-' 表示输出到 stdout
accesslog = "/home/hrsystem/hr-backend/log/accesslog.log"
# 错误日志路径，'-' 表示输出到 stderr
errorlog = "/home/hrsystem/hr-backend/log/errorlog.log"
# 日志级别：debug, info, warning, error, critical
loglevel = "info"

# --- 性能与安全 ---
# 限制请求行大小 (防止 HTTP 攻击)
limit_request_line = 4094
# 限制请求头字段数量
limit_request_fields = 100
# 限制请求头字段大小
limit_request_field_size = 8190

# --- 进程管理 ---
# 是否在 master 进程中预加载应用 (节省内存，但需注意数据库连接 fork 问题)
preload_app = False

# --- 钩子函数 (可选) ---
def on_starting(server):
    print("Gunicorn is starting...")

def on_reload(server):
    print("Gunicorn is reloading...")

def worker_int(worker):
    print(f"Worker {worker.pid} received INT signal")