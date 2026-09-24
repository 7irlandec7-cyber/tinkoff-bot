#!/usr/bin/env python3
"""
Watchdog-демон для скальпинг-бота Tinkoff.
Использует double-fork daemonization для полного отсоединения от родителя.
"""
import os
import sys
import time
import subprocess

SCRIPT_DIR = "/home/user/tinkoff-mcp"
LOG_FILE = "/tmp/bot.log"
WATCHDOG_LOG = "/tmp/watchdog.log"
PID_FILE = "/tmp/bot.pid"
WATCHDOG_PID_FILE = "/tmp/watchdog.pid"
STOP_FILE = "/tmp/bot.stop"
PYTHON = f"{SCRIPT_DIR}/venv/bin/python"
BOT_SCRIPT = f"{SCRIPT_DIR}/run_scalping_bot.py"

# --- Daemonization (double-fork) ---
def daemonize():
    """Стандартная UNIX daemon процедура."""
    # Первый fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)  # Родитель выходит

    # Создаём новую сессию
    os.setsid()

    # Второй fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)  # Родитель (первый ребёнок) выходит

    # Теперь мы daemon
    os.chdir(SCRIPT_DIR)

    # Перенаправляем stdio
    sys.stdout.flush()
    sys.stderr.flush()
    with open('/dev/null', 'rb', 0) as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(WATCHDOG_LOG, 'ab', 0) as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())

    # Записываем PID
    with open(WATCHDOG_PID_FILE, 'w') as f:
        f.write(str(os.getpid()))


def is_bot_running():
    """Проверить, запущен ли бот."""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'run_scalping_bot.py'],
            capture_output=True, text=True
        )
        return result.returncode == 0 and result.stdout.strip()
    except Exception:
        return False


def start_bot():
    """Запустить бота в отсоединённом режиме."""
    try:
        # Активируем venv через вызов скрипта
        subprocess.Popen(
            [PYTHON, BOT_SCRIPT],
            cwd=SCRIPT_DIR,
            stdout=open(LOG_FILE, 'ab'),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # setsid внутри
            close_fds=True,
        )
        log(f"Bot started")
        time.sleep(15)  # Ждём чтобы бот стартовал
    except Exception as e:
        log(f"ERROR starting bot: {e}")


def log(msg):
    """Записать в лог с timestamp."""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)


def main():
    daemonize()
    log(f"Watchdog daemon started (PID {os.getpid()})")

    try:
        while True:
            # Проверка флага остановки
            if os.path.exists(STOP_FILE):
                log(f"Stop file detected, exiting")
                try:
                    os.remove(STOP_FILE)
                except OSError:
                    pass
                # Убиваем бота
                subprocess.run(['pkill', '-9', '-f', 'run_scalping_bot.py'])
                sys.exit(0)

            # Проверка бота
            if is_bot_running():
                time.sleep(30)
            else:
                log("Bot NOT running, starting...")
                start_bot()

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        log(f"FATAL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
