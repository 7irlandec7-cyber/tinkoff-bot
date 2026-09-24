#!/bin/bash
# Watchdog для скальпинг-бота Tinkoff (улучшенная версия).
# Полностью отсоединяется от родительского процесса через setsid + nohup.
# Перезапускает бота при падении каждые 30 секунд.
# Не требует AI credentials - чистый bash + python.

SCRIPT_DIR="/home/user/tinkoff-mcp"
LOG_FILE="/tmp/bot.log"
WATCHDOG_LOG="/tmp/watchdog.log"
PYTHON="$SCRIPT_DIR/venv/bin/python"
BOT_SCRIPT="$SCRIPT_DIR/run_scalping_bot.py"

# Файл-флаг для остановки (touch /tmp/bot.stop для остановки watchdog)
STOP_FILE="/tmp/bot.stop"

cd "$SCRIPT_DIR" || exit 1

# Полное отсоединение от терминала
exec </dev/null >"$WATCHDOG_LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Watchdog v2 started (PID $$)"

while true; do
	# Проверяем флаг остановки
	if [ -f "$STOP_FILE" ]; then
		echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stop file detected, exiting"
		rm -f "$STOP_FILE"
		# Убиваем бота
		pkill -9 -f "run_scalping_bot.py" 2>/dev/null
		exit 0
	fi

	# Проверяем, запущен ли бот
	if pgrep -f "run_scalping_bot.py" >/dev/null; then
		# Бот работает
		sleep 30
	else
		# Бот не запущен - запускаем
		echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot NOT running, starting..."

		# Активируем venv и запускаем с полным отсоединением
		(
			source "$SCRIPT_DIR/venv/bin/activate"
			setsid nohup "$PYTHON" "$BOT_SCRIPT" >>"$LOG_FILE" 2>&1 </dev/null &
			BOT_PID=$!
			disown $BOT_PID 2>/dev/null
			echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot started PID=$BOT_PID"
		)

		# Ждём немного чтобы бот успел стартовать
		sleep 15
	fi
done
