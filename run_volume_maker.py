#!/usr/bin/env python3
"""
Главная программа торговли объемами

Быстрая торговля объемами через двусторонние лимитные ордера
"""

# 🔥 Загрузка переменных окружения (должна быть перед другими импортами)
from dotenv import load_dotenv
from pathlib import Path
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

from core.services.volume_maker.terminal_ui import VolumeMakerTerminalUI
from core.services.volume_maker.models.volume_maker_config import VolumeMakerConfig
from core.services.volume_maker.implementations.volume_maker_service_impl import VolumeMakerServiceImpl
from core.adapters.exchanges.interface import ExchangeConfig, ExchangeType
from core.adapters.exchanges.factory import get_exchange_factory
import asyncio
import signal
import sys
from typing import Optional
import yaml

# Добавление корневой директории проекта в путь
sys.path.insert(0, str(Path(__file__).parent))


class VolumeMakerApp:
    """Приложение торговли объемами"""

    def __init__(self, config_file: str):
        """
        Инициализация приложения

        Args:
            config_file: Путь к файлу конфигурации
        """
        self.config_file = config_file
        self.config: Optional[VolumeMakerConfig] = None
        self.service: Optional[VolumeMakerServiceImpl] = None
        self.ui: Optional[VolumeMakerTerminalUI] = None
        self.adapter = None
        self._stop_requested = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _setup_signal_handlers(self):
        """Настройка обработчиков сигналов (должна быть вызвана в цикле событий)"""
        def signal_handler():
            """Обработчик сигналов"""
            print("\n\n🛑 Обнаружен сигнал остановки, безопасный выход...")
            self._stop_requested = True

            # 🔥 Критическое исправление: остановка UI (это позволит циклу UI выйти)
            if self.ui:
                self.ui.stop()

            # Остановка сервиса
            if self.service and self.service.is_running():
                # Планирование задачи остановки в цикле событий
                asyncio.create_task(self._safe_stop())

        # Регистрация обработки сигналов (только на Unix системах)
        try:
            if self._loop and hasattr(self._loop, 'add_signal_handler'):
                for sig in (signal.SIGINT, signal.SIGTERM):
                    self._loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows не поддерживает add_signal_handler, полагаемся на KeyboardInterrupt
            pass

    async def _safe_stop(self):
        """Безопасная остановка сервиса"""
        try:
            print("⏸️  Остановка сервиса...")
            if self.service:
                await self.service.stop()
            print("✅ Сервис остановлен")
        except Exception as e:
            print(f"⚠️  Ошибка при остановке сервиса: {e}")

    def load_config(self) -> bool:
        """Загрузка конфигурации"""
        try:
            config_path = Path(self.config_file)
            if not config_path.exists():
                print(f"❌ Файл конфигурации не существует: {config_path}")
                return False

            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            self.config = VolumeMakerConfig.from_dict(config_data)
            print(f"✅ Файл конфигурации успешно загружен: {config_path}")
            return True

        except Exception as e:
            print(f"❌ Ошибка загрузки файла конфигурации: {e}")
            return False

    def load_exchange_config(self) -> Optional[ExchangeConfig]:
        """Загрузка конфигурации биржи"""
        try:
            # Загрузка соответствующей конфигурации по имени биржи
            exchange_config_file = Path(
                "config/exchanges") / f"{self.config.exchange}_config.yaml"

            if not exchange_config_file.exists():
                print(f"❌ Файл конфигурации биржи не существует: {exchange_config_file}")
                return None

            with open(exchange_config_file, 'r', encoding='utf-8') as f:
                exchange_data = yaml.safe_load(f)

            # Получение конфигурации биржи
            exchange_conf = exchange_data.get(self.config.exchange, {})

            # Получение конфигурации аутентификации (поддержка разных форматов)
            auth_conf = exchange_conf.get('authentication', {})
            api_conf = exchange_conf.get('api', {})

            # Backpack использует private_key, другие биржи используют api_secret
            api_secret = (
                auth_conf.get('private_key') or  # Формат Backpack
                exchange_conf.get('api_secret') or  # Прямая конфигурация
                auth_conf.get('api_secret') or  # В блоке аутентификации
                ''
            )

            api_key = (
                auth_conf.get('api_key') or  # В блоке аутентификации
                exchange_conf.get('api_key') or  # Прямая конфигурация
                ''
            )

            # 创建ExchangeConfig
            config = ExchangeConfig(
                exchange_id=self.config.exchange,
                name=exchange_conf.get('name', self.config.exchange),
                exchange_type=ExchangeType(exchange_conf.get('type', 'spot')),
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=exchange_conf.get(
                    'api_passphrase') or auth_conf.get('api_passphrase'),
                testnet=exchange_conf.get('testnet', False) or exchange_conf.get(
                    'development', {}).get('sandbox', False),
                base_url=api_conf.get(
                    'base_url') or exchange_conf.get('base_url'),
                ws_url=api_conf.get('ws_url') or exchange_conf.get('ws_url'),
                default_leverage=exchange_conf.get('default_leverage', 1),
                default_margin_mode=exchange_conf.get(
                    'default_margin_mode', 'cross')
            )

            # Проверка загрузки API ключей
            if api_key and api_secret:
                # Отображение части ключа для подтверждения (в целях безопасности показываем только первые и последние символы)
                masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(
                    api_key) > 12 else "***"
                masked_secret = f"{api_secret[:8]}...{api_secret[-4:]}" if len(
                    api_secret) > 12 else "***"
                print(f"✅ Конфигурация биржи успешно загружена: {self.config.exchange}")
                print(f"   API Key: {masked_key}")
                print(f"   API Secret: {masked_secret}")
            else:
                print(f"⚠️  Предупреждение: API ключи не настроены или настроены не полностью")
                if not api_key:
                    print(f"   Отсутствует API Key")
                if not api_secret:
                    print(f"   Отсутствует API Secret (или private_key)")

            return config

        except Exception as e:
            print(f"❌ Ошибка загрузки конфигурации биржи: {e}")
            return None

    async def initialize(self) -> bool:
        """Инициализация"""
        try:
            # Загрузка конфигурации
            if not self.load_config():
                return False

            # Загрузка конфигурации биржи
            exchange_config = self.load_exchange_config()
            if not exchange_config:
                return False

            # Создание адаптера биржи
            print(f"🔧 Создание адаптера {self.config.exchange}...")
            factory = get_exchange_factory()
            self.adapter = factory.create_adapter(
                exchange_id=self.config.exchange,
                config=exchange_config
            )

            # Создание сервиса торговли объемами
            print("🔧 Создание сервиса торговли объемами...")
            self.service = VolumeMakerServiceImpl(self.adapter)

            # Инициализация сервиса
            print("🔧 Инициализация сервиса торговли объемами...")
            if not await self.service.initialize(self.config):
                return False

            # Создание терминального UI
            if self.config.ui.enabled:
                print("🔧 Создание терминального UI...")
                self.ui = VolumeMakerTerminalUI(self.service)

            print("✅ Инициализация завершена")
            return True

        except Exception as e:
            print(f"❌ Ошибка инициализации: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def run(self) -> None:
        """Запуск приложения"""
        try:
            # Получение текущего цикла событий и настройка обработчиков сигналов
            self._loop = asyncio.get_running_loop()
            self._setup_signal_handlers()

            # Запуск сервиса
            print("🚀 Запуск сервиса торговли объемами...")
            await self.service.start()

            # Если UI включен, запуск UI
            if self.ui:
                print("🎨 Запуск терминального UI...")
                # Запуск UI в задаче, чтобы можно было реагировать на сигнал остановки
                ui_task = asyncio.create_task(self.ui.run())

                # Ожидание завершения UI или запроса на остановку
                while not self._stop_requested and self.service.is_running():
                    await asyncio.sleep(0.5)
                    if ui_task.done():
                        break

                # Если запрос на остановку, отмена задачи UI
                if not ui_task.done():
                    ui_task.cancel()
                    try:
                        await ui_task
                    except asyncio.CancelledError:
                        pass
            else:
                # Иначе ожидание завершения сервиса или запроса на остановку
                while not self._stop_requested and self.service.is_running():
                    await asyncio.sleep(0.5)

        except KeyboardInterrupt:
            print("\n\n🛑 Обнаружен Ctrl+C, остановка...")
        except Exception as e:
            print(f"❌ Ошибка выполнения: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """Очистка ресурсов"""
        try:
            print("\n🧹 Очистка ресурсов...")

            # Остановка UI
            if self.ui:
                try:
                    self.ui.stop()
                    print("  ✅ UI остановлен")
                except Exception as e:
                    print(f"  ⚠️  Ошибка остановки UI: {e}")

            # Остановка сервиса (с защитой по таймауту)
            if self.service and self.service.is_running():
                try:
                    print("  ⏸️  Остановка сервиса торговли объемами...")
                    await asyncio.wait_for(self.service.stop(), timeout=10.0)
                    print("  ✅ Сервис торговли объемами остановлен")
                except asyncio.TimeoutError:
                    print("  ⚠️  Таймаут остановки сервиса (10 секунд)")
                except Exception as e:
                    print(f"  ⚠️  Ошибка остановки сервиса: {e}")

            # Отключение от биржи (с защитой по таймауту)
            if self.adapter and hasattr(self.adapter, 'is_connected'):
                try:
                    if self.adapter.is_connected():
                        print("  ⏸️  Отключение от биржи...")
                        await asyncio.wait_for(self.adapter.disconnect(), timeout=5.0)
                        print("  ✅ Соединение с биржей разорвано")
                except asyncio.TimeoutError:
                    print("  ⚠️  Таймаут отключения (5 секунд)")
                except Exception as e:
                    print(f"  ⚠️  Ошибка отключения: {e}")

            print("\n✅ Очистка завершена\n")

        except Exception as e:
            print(f"\n⚠️  Ошибка процесса очистки: {e}\n")


async def main():
    """Главная функция"""
    # Файл конфигурации по умолчанию
    config_file = "config/volume_maker/backpack_btc_volume_maker.yaml"

    # Получение файла конфигурации из аргументов командной строки
    if len(sys.argv) > 1:
        config_file = sys.argv[1]

    print("=" * 60)
    print("🎯 Система торговли объемами v1.0")
    print("=" * 60)
    print(f"Файл конфигурации: {config_file}")
    print()

    # Создание приложения
    app = VolumeMakerApp(config_file)

    # Инициализация
    if not await app.initialize():
        print("❌ Ошибка инициализации, выход из программы")
        return

    # Запуск
    await app.run()

    print()
    print("=" * 60)
    print("👋 Программа завершена")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрограмма прервана пользователем")
    except Exception as e:
        print(f"Аварийный выход программы: {e}")
        import traceback
        traceback.print_exc()
