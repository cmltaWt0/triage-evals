from pixloom import decode_png


def thumbnail(data: bytes) -> bytes:
    return decode_png(data).resize(128)
