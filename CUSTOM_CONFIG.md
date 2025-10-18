# راهنمای استفاده از کانفیگ سفارشی

## توضیحات

این قابلیت به شما امکان می‌دهد تا `routing` و `outbounds` را برای هر نود به صورت سفارشی تنظیم کنید، در حالی که سازگاری کامل با نسخه قبلی حفظ می‌شود.

## نحوه استفاده

### 1. تنظیم متغیر محیطی

متغیر محیطی `XRAY_CONFIG_FILE` را به آدرس فایل JSON کانفیگ سفارشی خود تنظیم کنید:

```bash
export XRAY_CONFIG_FILE=/path/to/custom-config.json
```

یا در فایل `.env`:

```env
XRAY_CONFIG_FILE=/var/lib/marzban-node/custom-config.json
```

### 2. ایجاد فایل کانفیگ سفارشی

یک فایل JSON ایجاد کنید که شامل `routing` و/یا `outbounds` سفارشی شما باشد:

```json
{
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [
      {
        "type": "field",
        "ip": ["geoip:private"],
        "outboundTag": "BLOCK"
      },
      {
        "type": "field",
        "domain": ["geosite:category-ads-all"],
        "outboundTag": "BLOCK"
      }
    ]
  },
  "outbounds": [
    {
      "protocol": "freedom",
      "tag": "DIRECT"
    },
    {
      "protocol": "blackhole",
      "tag": "BLOCK"
    }
  ]
}
```

### 3. راه‌اندازی مجدد سرویس

پس از ایجاد فایل کانفیگ، سرویس را مجدداً راه‌اندازی کنید:

```bash
systemctl restart marzban-node
```

یا در Docker:

```bash
docker-compose restart
```

## نکات مهم

### سازگاری با نسخه قبلی ✅

- اگر `XRAY_CONFIG_FILE` تنظیم نشده یا فایل وجود نداشته باشد، سرویس دقیقاً مانند نسخه قبلی کار می‌کند
- هیچ تغییری در رفتار پیش‌فرض ایجاد نشده است

### Override جزئی

می‌توانید فقط یکی از بخش‌ها را override کنید:

**فقط routing:**
```json
{
  "routing": {
    "rules": [...]
  }
}
```

**فقط outbounds:**
```json
{
  "outbounds": [...]
}
```

### API Inbound

- قسمت API inbound همچنان به صورت خودکار توسط سرویس تزریق می‌شود
- قوانین routing مربوط به API نیز به صورت خودکار اضافه می‌شوند
- نیازی به تنظیم دستی API در کانفیگ سفارشی نیست

### Inbounds

بخش `inbounds` همچنان از پنل مرزبان دریافت می‌شود و در کانفیگ سفارشی لحاظ نمی‌شود. فقط `routing` و `outbounds` قابل override هستند.

## مثال استفاده با Docker Compose

```yaml
version: '3.8'

services:
  marzban-node:
    image: gozargah/marzban-node:latest
    restart: always
    network_mode: host
    environment:
      SERVICE_PORT: 62050
      XRAY_API_PORT: 62051
      XRAY_CONFIG_FILE: /var/lib/marzban-node/custom-config.json
    volumes:
      - /var/lib/marzban-node:/var/lib/marzban-node
      - ./custom-config.json:/var/lib/marzban-node/custom-config.json
```

## عیب‌یابی

اگر کانفیگ سفارشی بارگذاری نمی‌شود، لاگ‌ها را بررسی کنید:

```bash
journalctl -u marzban-node -f
```

یا در Docker:

```bash
docker logs -f marzban-node
```

پیام‌های زیر نشان می‌دهند که کانفیگ سفارشی با موفقیت بارگذاری شده است:

```
Loading custom routing from /path/to/custom-config.json
Loading custom outbounds from /path/to/custom-config.json
Custom config loaded successfully
```

## مثال‌های کاربردی

### مسدود کردن تبلیغات

```json
{
  "routing": {
    "domainStrategy": "IPOnDemand",
    "rules": [
      {
        "type": "field",
        "domain": [
          "geosite:category-ads-all",
          "geosite:category-ads-ir"
        ],
        "outboundTag": "BLOCK"
      }
    ]
  },
  "outbounds": [
    {
      "protocol": "freedom",
      "tag": "DIRECT"
    },
    {
      "protocol": "blackhole",
      "tag": "BLOCK"
    }
  ]
}
```

### مسیریابی بر اساس کشور

```json
{
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [
      {
        "type": "field",
        "domain": ["geosite:ir"],
        "outboundTag": "DIRECT"
      },
      {
        "type": "field",
        "ip": ["geoip:ir"],
        "outboundTag": "DIRECT"
      }
    ]
  },
  "outbounds": [
    {
      "protocol": "freedom",
      "tag": "DIRECT"
    }
  ]
}
```

### استفاده از پروکسی چند لایه

```json
{
  "outbounds": [
    {
      "protocol": "freedom",
      "tag": "DIRECT"
    },
    {
      "protocol": "vmess",
      "tag": "RELAY",
      "settings": {
        "vnext": [
          {
            "address": "relay.example.com",
            "port": 443,
            "users": [
              {
                "id": "your-uuid-here",
                "alterId": 0
              }
            ]
          }
        ]
      }
    }
  ],
  "routing": {
    "rules": [
      {
        "type": "field",
        "network": "tcp,udp",
        "outboundTag": "RELAY"
      }
    ]
  }
}
```
