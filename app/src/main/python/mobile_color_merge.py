"""
mobile_color_merge.py - Técnicas de cor da v0.8.4 do PC (color_merge.py) em NumPy + Pillow.
O Chaquopy não tem OpenCV para Python 3.11, então Lab, desfoque e k-means foram reescritos aqui,
com as mesmas fórmulas do OpenCV (Lab 8 bits: L*255/100, a e b + 128, branco D65, gama sRGB).
- merge_lineart: traço original por cima da cor; pele natural (antes estourava para amarelo pálido).
- descreen: retícula vira sombra lisa (manchas de pele molhada viravam hematomas, céu granulado).
- consolidate_colors: uma peça, uma cor (moletom rosa/roxo/azul, saia jeans em manchas).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import numpy as np
from PIL import Image, ImageFilter

# Mesmos valores do PC, ajustados comparando com a colorização oficial de uma obra
PAPER_BLEND = 0.5  # quanto clarear na direção do papel original (0 = cores escuras, 1 = pele estourada)
COLOR_SATURATION = 0.7  # intensidade final das cores (1 = como o modelo entrega)
DESCREEN_SIGMA = 1.5  # suavização da retícula numa página de 1500 px (escala com o tamanho)
PALETTE_SIZE = 8  # 6 já manchava a pele de branco; 8 manteve pele e cabelo e uniformizou as roupas
PALETTE_PULL = 0.7  # quanto puxar para a paleta (1 = cor chapada)
PALETTE_SOFTNESS = 10.0  # mistura as cores vizinhas da paleta: sem isso, a pele ganhava manchas brancas

_WHITE = np.array([0.950456, 1.0, 1.088754], np.float32)
_RGB2XYZ = np.array([[0.412453, 0.357580, 0.180423],
                     [0.212671, 0.715160, 0.072169],
                     [0.019334, 0.119193, 0.950227]], np.float32)
_XYZ2RGB = np.linalg.inv(_RGB2XYZ).astype(np.float32)


def _f(t):
    return np.where(t > 0.008856, np.cbrt(t), 7.787 * t + 16.0 / 116.0)


def _f_inv(t):
    return np.where(t > 0.206893, t ** 3, (t - 16.0 / 116.0) / 7.787)


def rgb_to_lab(rgb):
    """RGB uint8 (H, W, 3) -> Lab float32 na escala 8 bits do OpenCV."""
    c = rgb.astype(np.float32) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = lin @ _RGB2XYZ.T / _WHITE
    fx, fy, fz = _f(xyz[..., 0]), _f(xyz[..., 1]), _f(xyz[..., 2])
    y = xyz[..., 1]
    light = np.where(y > 0.008856, 116.0 * fy - 16.0, 903.3 * y)
    return np.stack([light * 255.0 / 100.0, 500.0 * (fx - fy) + 128.0, 200.0 * (fy - fz) + 128.0], axis=-1)


def lab_to_rgb(lab):
    """Lab float (escala 8 bits do OpenCV) -> RGB uint8."""
    light = lab[..., 0] * 100.0 / 255.0
    fy = (light + 16.0) / 116.0
    fx = fy + (lab[..., 1] - 128.0) / 500.0
    fz = fy - (lab[..., 2] - 128.0) / 200.0
    xyz = np.stack([_f_inv(fx), _f_inv(fy), _f_inv(fz)], axis=-1) * _WHITE
    lin = np.clip(xyz @ _XYZ2RGB.T, 0.0, 1.0)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(c * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _gray_lightness(gray):
    """L (Lab 8 bits) de uma imagem cinza, sem montar a imagem colorida inteira."""
    lut = rgb_to_lab(np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, axis=1)[None])[0, :, 0]
    return lut[gray]


def descreen(gray):
    """Retícula (pontinhos) vira sombra lisa; traço de verdade (escuro com vizinhança escura) fica nítido."""
    sigma = max(0.6, DESCREEN_SIGMA * max(gray.shape[:2]) / 1500.0)
    smooth = np.asarray(Image.fromarray(gray).filter(ImageFilter.GaussianBlur(sigma)))
    line = (gray < 110) & (smooth < 150)
    return np.where(line, gray, smooth).astype(np.uint8)


def merge_lineart(color_rgb, gray):
    """Traço e retícula originais por cima da cor (Lab): clareia na direção do papel e nunca passa do traço."""
    lab = rgb_to_lab(color_rgb)
    ink = _gray_lightness(descreen(gray))
    new_l = np.minimum(lab[..., 0] * (1 - PAPER_BLEND) + ink * PAPER_BLEND, ink)
    keep = (np.minimum(new_l / np.maximum(lab[..., 0], 1.0), 1.0) * COLOR_SATURATION)[..., None]
    lab[..., 1:] = 128.0 + (lab[..., 1:] - 128.0) * keep
    lab[..., 0] = new_l
    return lab_to_rgb(lab)


def _kmeans(points, k, iters=30, seed=0):
    """k-means++ simples e determinístico (equivalente ao cv2.kmeans usado no PC)."""
    rng = np.random.default_rng(seed)
    centers = [points[rng.integers(len(points))]]
    for _ in range(1, k):
        d2 = np.min(((points[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        total = d2.sum()
        if total <= 0:
            break
        centers.append(points[rng.choice(len(points), p=d2 / total)])
    centers = np.array(centers, np.float32)
    for _ in range(iters):
        labels = ((points[:, None, :] - centers[None]) ** 2).sum(-1).argmin(1)
        moved = np.array([points[labels == i].mean(0) if np.any(labels == i) else centers[i]
                          for i in range(len(centers))], np.float32)
        if np.abs(moved - centers).max() < 0.5:
            return moved
        centers = moved
    return centers


def consolidate_colors(color_rgb):
    """Uma peça, uma cor: puxa cada pixel para as cores principais da página (k-means em a/b).
    Só a cor muda; o brilho e as sombras do modelo ficam."""
    lab = rgb_to_lab(color_rgb)
    ab = lab[..., 1:].reshape(-1, 2)
    sample = ab[:: max(1, ab.shape[0] // 60000)]
    if len(np.unique(sample.astype(np.uint8), axis=0)) < 2:
        return color_rgb
    centers = _kmeans(sample, min(PALETTE_SIZE, len(sample)))
    target = np.empty_like(ab)
    for start in range(0, ab.shape[0], 200000):  # em blocos: celular tem pouca memória
        part = ab[start:start + 200000]
        dist2 = ((part[:, None, :] - centers[None]) ** 2).sum(-1)
        weights = np.exp(-(dist2 - dist2.min(1, keepdims=True)) / (2 * PALETTE_SOFTNESS ** 2))
        target[start:start + 200000] = (weights @ centers) / weights.sum(1, keepdims=True)
    lab[..., 1:] = lab[..., 1:] * (1 - PALETTE_PULL) + target.reshape(lab.shape[0], lab.shape[1], 2) * PALETTE_PULL
    return lab_to_rgb(lab)
