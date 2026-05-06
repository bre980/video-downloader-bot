# استخدام نسخة بايثون رسمية ومستقرة
FROM python:3.11-slim

# تثبيت التبعات اللازمة للنظام (ffmpeg ضروري لتحويل الصوت)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات الكود
COPY . .

# إنشاء مجلد التحميلات
RUN mkdir -p downloads

# فتح المنفذ الذي يستخدمه Render (افتراضياً 8080)
EXPOSE 8080

# تشغيل البوت
CMD ["python", "bot.py"]
