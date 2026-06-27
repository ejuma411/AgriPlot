# databases_temp.py - ONLY for data migration, delete after use
import os

DATABASES = {
    'local': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('LOCAL_DB_NAME', 'agriplot_db'),
        'USER': os.environ.get('LOCAL_DB_USER', 'createch'),
        'PASSWORD': os.environ.get('LOCAL_DB_PASSWORD'),
        'HOST': os.environ.get('LOCAL_DB_HOST', 'localhost'),
        'PORT': os.environ.get('LOCAL_DB_PORT', '5432'),
    },
    'supabase': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('SUPABASE_DB_NAME'),
        'USER': os.environ.get('SUPABASE_DB_USER'),
        'PASSWORD': os.environ.get('SUPABASE_DB_PASSWORD'),
        'HOST': os.environ.get('SUPABASE_DB_HOST'),
        'PORT': os.environ.get('SUPABASE_DB_PORT', '5432'),
        'OPTIONS': {
            'sslmode': 'require',
        },
    }
}