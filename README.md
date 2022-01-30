# Assistant

Модуль для выполнения вспомогательных периодических задач для релизного бота и администраторов.

БД - в Postgres, кластер PGTools

Все запуски производятся из шедулера (модуль python), с расписанием:
```python
scheduler.add_job(duty_reminder_daily_morning, 'cron', day_of_week='*',  hour=9, minute=45)
```

## Деплой

Ansible - забирает секреты из Vault

Helm - шаблонизирует конфиги для K8s

Выкатка контейнера происходит в кластер Intools, по мёржу
