"""Losslessly stitch 2-pass or 4-pass character renders into the H3 16:9 4-panel sheet layout.

Layout matches assets/character-reference-layout-r2.png (borderless 16:9):
- Left 1/3:   front full-body (head-to-toe preserved, never vertically clipped)
- Middle top: frontal head-and-shoulders close-up
- Middle bot: side / three-quarter profile close-up
- Right 1/3:  rear full-body (head-to-toe preserved, never vertically clipped)
"""
import argparse
from pathlib import Path
from PIL import Image, ImageOps


def parse_size(text: str) -> tuple[int, int]:
    try:
        w_str, h_str = text.lower().split('x', 1)
        w, h = int(w_str), int(h_str)
    except ValueError as exc:
        raise ValueError(f'尺寸格式须为 宽x高（如 3344x1882 或 3840x2160），当前：{text}') from exc
    if w < 1600 or h < 900 or abs((w / h) - (16 / 9)) > 0.02:
        raise ValueError(f'输出尺寸须为高清 16:9（至少 1600x900），当前：{w}x{h}')
    return w, h


def fit_full_body(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Fit a standing full-body render to target_w x target_h while preserving 100% vertical height."""
    img = img.convert('RGB')
    src_w, src_h = img.size
    scaled_w = max(1, round(src_w * (target_h / src_h)))
    resized = img.resize((scaled_w, target_h), Image.Resampling.LANCZOS)
    if scaled_w == target_w:
        return resized
    if scaled_w > target_w:
        left = (scaled_w - target_w) // 2
        return resized.crop((left, 0, left + target_w, target_h))
    # Source is narrower than 1/3 of 16:9: pad left/right using outer backdrop strips so head/feet never clip.
    canvas = Image.new('RGB', (target_w, target_h))
    pad_left = (target_w - scaled_w) // 2
    pad_right = target_w - scaled_w - pad_left
    if pad_left > 0:
        left_strip = resized.crop((0, 0, 1, target_h)).resize((pad_left, target_h), Image.Resampling.BILINEAR)
        canvas.paste(left_strip, (0, 0))
    canvas.paste(resized, (pad_left, 0))
    if pad_right > 0:
        right_strip = resized.crop((scaled_w - 1, 0, scaled_w, target_h)).resize(
            (pad_right, target_h), Image.Resampling.BILINEAR
        )
        canvas.paste(right_strip, (pad_left + scaled_w, 0))
    return canvas


def fit_portrait(img: Image.Image, target_w: int, target_h: int, y_bias: float = 0.42) -> Image.Image:
    """Cover-fit a close-up portrait to target_w x target_h with eye-level vertical bias."""
    return ImageOps.fit(img.convert('RGB'), (target_w, target_h), method=Image.Resampling.LANCZOS, centering=(0.5, y_bias))


def split_lr(img: Image.Image) -> tuple[Image.Image, Image.Image]:
    w, h = img.size
    mid = w // 2
    return img.crop((0, 0, mid, h)), img.crop((mid, 0, w, h))


def stitch(
    front_body: Image.Image,
    front_face: Image.Image,
    side_face: Image.Image,
    back_body: Image.Image,
    size: tuple[int, int] = (3344, 1882),
) -> Image.Image:
    total_w, total_h = size
    col_left = round(total_w / 3)
    col_right = round(total_w / 3)
    col_mid = total_w - col_left - col_right
    row_top = total_h // 2
    row_bot = total_h - row_top

    canvas = Image.new('RGB', (total_w, total_h))
    canvas.paste(fit_full_body(front_body, col_left, total_h), (0, 0))
    canvas.paste(fit_portrait(front_face, col_mid, row_top), (col_left, 0))
    canvas.paste(fit_portrait(side_face, col_mid, row_bot), (col_left, row_top))
    canvas.paste(fit_full_body(back_body, col_right, total_h), (col_left + col_mid, 0))
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--front-body', type=Path, help='正面全身图路径')
    parser.add_argument('--front-face', type=Path, help='正面面部特写图路径')
    parser.add_argument('--side-face', type=Path, help='侧面/斜侧面部特写图路径')
    parser.add_argument('--back-body', type=Path, help='背面全身图路径')
    parser.add_argument('--body-pair', type=Path, help='双拼全身图路径（左正面全身、右背面全身）')
    parser.add_argument('--face-pair', type=Path, help='双拼特写图路径（左正面近景、右侧面近景）')
    parser.add_argument('--output', type=Path, required=True, help='输出16:9四视角整图路径（.png）')
    parser.add_argument('--size', default='3344x1882', help='输出分辨率，默认 3344x1882（可选 3840x2160）')
    args = parser.parse_args()

    try:
        target_size = parse_size(args.size)
        four_mode = all([args.front_body, args.front_face, args.side_face, args.back_body])
        pair_mode = bool(args.body_pair and args.face_pair)
        if four_mode == pair_mode:
            raise ValueError('请提供四张独立分图（--front-body/--front-face/--side-face/--back-body）或两张双拼图（--body-pair + --face-pair）。')

        if four_mode:
            fb = Image.open(args.front_body)
            ff = Image.open(args.front_face)
            sf = Image.open(args.side_face)
            bb = Image.open(args.back_body)
        else:
            fb, bb = split_lr(Image.open(args.body_pair))
            ff, sf = split_lr(Image.open(args.face_pair))

        result = stitch(fb, ff, sf, bb, size=target_size)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.save(args.output, format='PNG', optimize=True)
        print(f'已生成四视角高清人设图：{args.output} ({result.size[0]}x{result.size[1]})')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
