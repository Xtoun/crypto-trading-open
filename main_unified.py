#!/usr/bin/env python3
"""
Унифицированный скрипт запуска системы сегментированного арбитража (рефакторинг)

Использование:
    python main_unified.py

Функции:
    - Использование нового единого движка решений (алгоритм, управляемый общим количеством)
    - Поддержка независимой конфигурации для нескольких торговых пар
    - Поддержка режима скальпинга
    - Поддержка разделенного исполнения
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path
from typing import Optional

# 🔥 Автоматическое исправление SSL сертификатов (перед импортом всех сетевых библиотек)
# Принудительное использование корневых сертификатов от certifi, решает проблему SSL верификации в macOS внешнем терминале
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    # print(f"🔐 Путь SSL сертификата принудительно указан: {certifi.where()}")
except ImportError:
    print("⚠️  Библиотека certifi не найдена, SSL верификация может не работать во внешнем терминале")

# Добавление корневой директории проекта в путь
sys.path.insert(0, str(Path(__file__).parent))

# 🔥 Загрузка переменных окружения (должна быть перед импортом других модулей)
from dotenv import load_dotenv
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ Переменные окружения загружены: {env_path}")
else:
    print(f"⚠️  Файл .env не найден: {env_path}")
    print("💡 Для настройки API-ключей создайте файл .env")

from core.services.arbitrage_monitor_v2.core.unified_orchestrator import UnifiedOrchestrator
from core.services.arbitrage_monitor_v2.config.debug_config import DebugConfig


def parse_args():
    """Разбор аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description="Унифицированный скрипт запуска системы сегментированного арбитража (рефакторинг)"
    )
    
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/arbitrage/arbitrage_segmented.yaml"),
        help="Путь к файлу сегментированной конфигурации"
    )
    
    parser.add_argument(
        "--monitor-config",
        type=Path,
        default=Path("config/arbitrage/monitor_v2.yaml"),
        help="Путь к файлу конфигурации мониторинга"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Включить режим отладки"
    )
    
    return parser.parse_args()


async def main():
    """Главная точка входа"""
    args = parse_args()
    
    # Настройка опций отладки
    if args.debug:
        debug_config = DebugConfig.create_basic()
        print("🔧 Режим отладки включен (Basic)")
    else:
        debug_config = DebugConfig.create_production()
    orchestrator: Optional[UnifiedOrchestrator] = None
    try:
        # Инициализация единого оркестратора
        orchestrator = UnifiedOrchestrator(
            segmented_config_path=args.config,
            monitor_config_path=args.monitor_config,
            debug_config=debug_config
        )

        # Запуск системы
        await orchestrator.start()
        
        # Поддержание работы
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Программа остановлена пользователем")
    except Exception as e:
        print(f"\n❌ Аварийный выход программы: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Логика изящного завершения (если orchestrator предоставляет метод stop)
        if orchestrator and hasattr(orchestrator, 'stop'):
            print("Закрытие оркестратора...")
            await orchestrator.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
