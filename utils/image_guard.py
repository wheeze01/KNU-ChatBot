import io, requests
from PIL import Image, ImageOps

MAX_BYTES = 4 * 1024 * 1024      # 4MB
MAX_DIM   = 10_000               # 긴 변 제한
TIMEOUT   = (10, 15)             # (connect, read)

def _download(url: str) -> tuple[bytes, str]:
    r = requests.get(url, stream=True, timeout=TIMEOUT)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "")
    data = r.content
    return data, ctype

def _to_rgb(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode not in ("RGB", "L"):
        return im.convert("RGB")
    return im if im.mode == "RGB" else im.convert("RGB")

def _shrink_long_edge(im: Image.Image, max_edge=MAX_DIM) -> Image.Image:
    w, h = im.size
    if max(w, h) <= max_edge:
        return im
    ratio = max_edge / float(max(w, h))
    return im.resize((int(w*ratio), int(h*ratio)), Image.Resampling.LANCZOS)

def _jpeg_under_4mb(im: Image.Image) -> bytes:
    # 간단 품질 이분탐색: 35~95 범위에서 4MB 이하 맞추기
    low, high, best = 35, 95, None
    while low <= high:
        q = (low + high) // 2
        bio = io.BytesIO()
        im.save(bio, format="JPEG", quality=q, optimize=True, progressive=True, subsampling="4:2:0")
        size = bio.tell()
        if size <= MAX_BYTES:
            best = bio.getvalue()
            low = q + 1
        else:
            high = q - 1
    if best is None:
        # 최저 품질로도 4MB 초과면 해상도 0.8배로 줄여서 한 번 더 시도
        im2 = _shrink_long_edge(im, int(MAX_DIM * 0.8))
        bio = io.BytesIO()
        im2.save(bio, format="JPEG", quality=35, optimize=True, progressive=True, subsampling="4:2:0")
        best = bio.getvalue()
    return best

def ensure_ocr_safe_bytes(url: str) -> tuple[bytes, str]:
    """
    URL → (OCR 안전 바이트, content_type)
    - PDF면 그대로 반환
    - 그 외 이미지: 10k px 이하 축소 + JPEG 변환 + 4MB 이하 압축
    """
    data, ctype = _download(url)

    # PDF는 Read API가 직접 지원 → 그대로 반환
    if (ctype or "").startswith("application/pdf") or url.lower().endswith(".pdf"):
        return data, "application/pdf"

    # 이미지 처리 (손상/미지원 포맷이면 예외 발생 → 호출쪽에서 잡아 스킵)
    bio = io.BytesIO(data)
    with Image.open(bio) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        im = _shrink_long_edge(im, MAX_DIM)
        im = _to_rgb(im)
        out = _jpeg_under_4mb(im)       # 항상 JPEG로 4MB 이하
        return out, "image/jpeg"
