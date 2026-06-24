import os
import zipfile
import tarfile
import shutil

try:
    import py7zr
    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False

def zip_files(file_paths, output_path):
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in file_paths:
            zipf.write(file, os.path.basename(file))
    return output_path

def unzip_file(zip_path, extract_to):
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        zipf.extractall(extract_to)
    return extract_to

def tar_files(file_paths, output_path, mode='w:gz'):
    with tarfile.open(output_path, mode) as tar:
        for file in file_paths:
            tar.add(file, arcname=os.path.basename(file))
    return output_path

def untar_file(tar_path, extract_to):
    with tarfile.open(tar_path, 'r:*') as tar:
        tar.extractall(extract_to)
    return extract_to

def seven_zip_files(file_paths, output_path):
    if not HAS_PY7ZR:
        raise ImportError("py7zr is not installed. Please install it with 'pip install py7zr'")
    with py7zr.SevenZipFile(output_path, 'w') as archive:
        for file in file_paths:
            archive.write(file, os.path.basename(file))
    return output_path

def unseven_zip_file(seven_zip_path, extract_to):
    if not HAS_PY7ZR:
        raise ImportError("py7zr is not installed. Please install it with 'pip install py7zr'")
    with py7zr.SevenZipFile(seven_zip_path, 'r') as archive:
        archive.extractall(extract_to)
    return extract_to
