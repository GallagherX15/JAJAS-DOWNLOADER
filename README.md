# JAJAS Downloader

Una aplicación de escritorio moderna, minimalista y funcional para descargar videos y playlists utilizando `yt-dlp` y `CustomTkinter`.

![Screenshot](https://via.placeholder.com/800x450.png?text=JAJAS+Downloader+Screenshot)

## Características

- 🎨 **Diseño Moderno**: Interfaz oscura tipo Windows 11 / macOS con bordes redondeados.
- 🔗 **Analizador Inteligente**: Pega una URL y detecta automáticamente si es un video individual o una playlist entera.
- 🎛️ **Modo Masivo e Individual**:
  - *Masivo*: Aplica la misma calidad y formato a toda la playlist con un clic.
  - *Individual*: Elige la resolución (4K, 1080p, etc.) o formato (MP4, MP3, WAV) de cada video por separado.
- ⚡ **Feedback en Tiempo Real**: Barra de progreso animada, velocidad de descarga real (MB/s) y tiempo estimado (ETA).

## Requisitos Previos

1. **Python 3.10** o superior.
2. **FFmpeg** instalado y agregado al `PATH` de tu sistema (necesario para conversiones de audio y video).

## Instalación

1. Clona el repositorio:
   ```bash
   git clone https://github.com/GallagherX15/JAJAS-DOWNLOADER.git
   cd JAJAS-DOWNLOADER
   ```

2. Crea y activa un entorno virtual (recomendado):
   ```bash
   python -m venv .venv
   # En Windows:
   .venv\Scripts\activate
   # En macOS/Linux:
   source .venv/bin/activate
   ```

3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

## Uso

Para ejecutar la aplicación, simplemente corre:

```bash
python main.py
```

1. **Pega la URL** del video o playlist en el buscador central y haz clic en "Analizar".
2. **Selecciona la carpeta** de destino.
3. Elige los formatos y calidades desde las listas desplegables.
4. Haz clic en **"Descargar"**.

## Licencia

Este proyecto se distribuye bajo la licencia MIT. Eres libre de usar, modificar y distribuir el código.
