# systemd 部署示例

```bash
sudo cp deploy/smart-invest.service /etc/systemd/system/
sudo cp deploy/smart-invest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smart-invest.timer
systemctl list-timers | grep smart-invest
```

手动触发一次：

```bash
sudo systemctl start smart-invest.service
journalctl -u smart-invest.service -n 100 --no-pager
```

如需调整日志保留天数（默认14天），可添加 override：

```bash
sudo systemctl edit smart-invest.service
# 添加：
# [Service]
# Environment=LOG_RETENTION_DAYS=30
```
