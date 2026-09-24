#!/bin/bash
# Быстрый и безопасный перезапуск скальпинг-бота Tinkoff.
# Использование: /home/user/tinkoff-mcp/restart_bot.sh
#
# ВАЖНО: нельзя использовать `pkill -f run_scalping_bot` из инлайн-команды —
# шаблон попадает в cmdline самого shell и убивает его. Здесь используем
# bracket-трюк (не совпадает с собственным cmdline) и kill по конкретным PID.

SCRIPT_DIR="/home/user/tinkoff-mcp"
LOG_FILE="/tmp/bot.log"

echo "=== Останавливаю старые процессы ==="
PIDS=$(pgrep -f "run_scalping_[b]ot.py|run_bot_[d]aemon.py" 2>/dev/null)
if [ -n "$PIDS" ]; then
	for pid in $PIDS; do
		kill -9 "$pid" 2>/dev/null && echo "  убит PID $pid"
	done
	sleep 3
else
	echo "  старых процессов нет"
fi

# Ротируем лог, чтобы новый запуск был виден с первой строки
if [ -f "$LOG_FILE" ]; then
	mv "$LOG_FILE" "/tmp/bot_prev_$(date +%Y%m%d_%H%M%S).log" 2>/dev/null
fi
: >"$LOG_FILE"

echo "=== Запускаю daemon (сам поднимет бота) ==="
cd "$SCRIPT_DIR" || exit 1
setsid nohup python3 "$SCRIPT_DIR/run_bot_daemon.py" </dev/null >/dev/null 2>&1 &
sleep 20

echo ""
echo "=== Статус процессов ==="
ps -eo pid,ppid,etime,cmd | grep -E "run_scalping_[b]ot.py|run_bot_[d]aemon.py"

echo ""
echo "=== Последние строки лога ==="
tail -n 15 "$LOG_FILE" 2>/dev/null
