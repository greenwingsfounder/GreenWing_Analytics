# setup.py

"""
GreenWing Analytics — Proje Kurulum Dosyası
════════════════════════════════════════════

Bu dosya projeyi pip ile kurulabilir paket haline getirir.

KULLANIM:
─────────
    # Geliştirme modunda kur (kod değişikliklerini anında yansıtır):
    pip install -e .

    # Normal kurulum:
    pip install .

NEDEN GEREKLİ:
──────────────
    1. from src.models.fuel_model import FuelModel
       gibi importların her yerden çalışmasını sağlar.

    2. Projeyi başka bir bilgisayara taşırken
       pip install -e . ile tek komutla kurulur.

    3. Profesyonellik göstergesi.
       Müşteri veya yatırımcı görürse "düzgün yapılmış" der.
"""

from setuptools import setup, find_packages

setup(
    # ─── Proje bilgileri ──────────────────────────────────
    name='greenWing-analytics',
    version='1.0.0',
    description='Aviation Fuel Efficiency & Emission Intelligence Platform',
    long_description=open('README.md', encoding='utf-8').read() if __import__('os').path.exists('README.md') else '',
    long_description_content_type='text/markdown',
    author='GreenWing Analytics',
    url='https://github.com/YOUR_USERNAME/greenWing-analytics',
    license='Proprietary',

    # ─── Python versiyonu ─────────────────────────────────
    python_requires='>=3.9',

    # ─── Paketler ─────────────────────────────────────────
    # find_packages() otomatik olarak tüm Python paketlerini bulur.
    # config/ ve src/ altındaki her __init__.py içeren klasör dahil.
    packages=find_packages(),

    # ─── Bağımlılıklar ────────────────────────────────────
    # requirements.txt ile aynı ama burada da belirtmek iyi pratik.
    install_requires=[
        'numpy>=1.21.0',
        'pandas>=1.3.0',
        'scipy>=1.7.0',
        'plotly>=5.3.0',
        'dash>=2.0.0',
        'dash-bootstrap-components>=1.0.0',
        'requests>=2.26.0',
        'pyyaml>=5.4.0',
        'python-dotenv>=0.19.0',
        'jinja2>=3.0.0',
        'openpyxl>=3.0.0',
        'loguru>=0.5.0',
        'tqdm>=4.62.0',
    ],

    # ─── Opsiyonel bağımlılıklar ──────────────────────────
    extras_require={
        'dev': [
            'pytest>=7.0.0',
            'pytest-cov>=3.0.0',
            'jupyter>=1.0.0',
            'jupyterlab>=3.0.0',
        ],
        'pdf': [
            'weasyprint>=53.0',
        ],
        'ml': [
            'scikit-learn>=1.0.0',
        ],
    },

    # ─── Paket verileri ───────────────────────────────────
    # YAML ve HTML şablon dosyalarını pakete dahil et.
    package_data={
        'config': ['*.yaml'],
        'src': ['reporting/templates/*.html', 'reporting/templates/*.css'],
    },
    include_package_data=True,

    # ─── Sınıflandırma ────────────────────────────────────
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Science/Research',
        'Topic :: Scientific/Engineering',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Operating System :: OS Independent',
        'License :: Other/Proprietary License',
    ],

    # ─── Anahtar kelimeler ────────────────────────────────
    keywords=[
        'aviation', 'fuel-efficiency', 'emission',
        'CORSIA', 'airline', 'optimization',
        'aerospace', 'flight-performance',
    ],
)
