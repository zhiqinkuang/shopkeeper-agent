"""
请求上下文模块

用于保存和传递一次请求或一次脚本执行过程中的上下文变量，
当前先维护 request_id，后续日志模块会从这里读取 request_id 并注入到每条日志中
"""

from contextvars import ContextVar

# 使用 ContextVar 而不是普通全局变量
# 是为了让并发协程之间的 request_id 互不干扰
# 默认值给命令行脚本用：脚本不会经过 FastAPI 中间件，没有人提前 set
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="1")