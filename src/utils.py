import time
import logging
import functools

def log_step(logger_name_or_logger=None):
    """
    A decorator that logs the entrance, exit, execution time, and any exceptions of a function.
    Uses logger.info for start/complete, and logger.error with tracebacks for failures.
    
    Usage:
        @log_step()
        def my_function():
            ...
            
        @log_step("my_custom_logger")
        def another_function():
            ...
    """
    def decorator(func):
        if isinstance(logger_name_or_logger, logging.Logger):
            log = logger_name_or_logger
        elif isinstance(logger_name_or_logger, str):
            log = logging.getLogger(logger_name_or_logger)
        else:
            log = logging.getLogger(func.__module__)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            func_name = func.__name__
            # Log calling parameters safely (skipping credentials if any)
            safe_args = [repr(a) for a in args]
            safe_kwargs = {k: repr(v) for k, v in kwargs.items()}
            
            # Mask common sensitive parameter keys in logs
            sensitive_keys = {"token", "key", "password", "secret"}
            for k in list(safe_kwargs.keys()):
                if any(sk in k.lower() for sk in sensitive_keys):
                    safe_kwargs[k] = "'[MASKED]'"
                    
            args_str = ", ".join(safe_args + [f"{k}={v}" for k, v in safe_kwargs.items()])
            log.info(f"▶️ Entering '{func_name}({args_str})'")
            
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                log.info(f"✅ Exited '{func_name}' successfully in {duration_ms:.2f}ms")
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                log.error(
                    f"❌ Exception in '{func_name}' after {duration_ms:.2f}ms: {type(e).__name__} - {e}",
                    exc_info=True
                )
                raise
        return wrapper
    return decorator
