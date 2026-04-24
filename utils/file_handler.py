import os,hashlib

from langchain_core.documents import Document
from utils.logger_handler import logger

# def get_file_md5_hex(file) -> str:
#     """计算文件的md5值"""
#     md5_obj = hashlib.md5()  # 创建md5对象
#     chunk_size = 4096
#     try:
#         while chunk := file.read(chunk_size):
#             md5_obj.update(chunk)
#
#         md5_hex = md5_obj.hexdigest()
#         return md5_hex
#     except Exception as e:
#         logger.error(f'[md5计算]文件{file.name}计算失败,{e}')
#     finally:
#         # 重置文件指针，以便后续读取
#         if hasattr(file, 'seek'):
#             file.seek(0)
def get_file_md5_hex(file) -> str:
    """计算文件的 md5 值，支持路径字符串、文件对象、UploadFile"""
    md5_obj = hashlib.md5()
    chunk_size = 4096

    try:
        if hasattr(file, 'file'):
            while chunk := file.file.read(chunk_size):
                if isinstance(chunk, str): chunk = chunk.encode('utf-8')
                md5_obj.update(chunk)
            file.file.seek(0)
        elif hasattr(file, 'read'):
            file.seek(0)
            while chunk := file.read(chunk_size):
                if isinstance(chunk, str): chunk = chunk.encode('utf-8')
                md5_obj.update(chunk)
            file.seek(0)
        else:
            with open(file, 'rb') as f:
                while chunk := f.read(chunk_size):
                    md5_obj.update(chunk)

        return md5_obj.hexdigest()
    except Exception as e:
        filename = getattr(file, 'filename', getattr(file, 'name', file))
        logger.error(f'[md5 计算] 文件{filename}计算失败,{e}')
        raise


def listdir_with_allowed_type(path: str, allowed_type: list[str] = ['.pdf', '.txt']) -> object:
    """查找文件夹内符合文件类型的文件"""
    file_list = []
    if not os.path.isdir(path):
        logger.error(f'[listdir_with_allowed_type]路径{path}不是文件夹')
        return file_list

    for file in os.listdir(path):
        if file.endswith(allowed_type):
            file_list.append(os.path.join(path,file))
    return file_list





def txt_loader(file):
    # return TextLoader(file_path=, encoding="utf-8").load()
    """从 UploadFile 读取文本并返回 Document 列表"""
    try:
        raw = file.read()
        if isinstance(raw, bytes):
            text = raw.decode('utf-8', errors='replace')
        else:
            text = raw
        doc = Document(page_content=text, metadata={'source': file.name or 'upload'})
        return [doc]
    except Exception as e:
        logger.error(f'[txt_loader] 读取文件{file.name}失败, {e}')
        return []



