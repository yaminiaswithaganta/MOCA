"""
Train the small back-up digit reader used by Task 3 (models/digits_hog_softmax.npz).

Why: the main reader (models/mnist-8.onnx) was trained on MNIST only and
misreads some printed-style digits people write on clocks (e.g. a "1" with a
flag read as "7"). This second model sees more styles; Task 3 averages the two.

Runtime needs only numpy + OpenCV (the weights are a plain .npz). Training
additionally uses scikit-learn and mlxtend (bundled 5k MNIST sample):
    pip install scikit-learn mlxtend
    python tools/train_digit_model.py
"""
import os
import sys

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from task3_clock_draw import _to_mnist, digit_features  # noqa: E402

TRAIN_FONTS = [cv2.FONT_HERSHEY_SIMPLEX, cv2.FONT_HERSHEY_PLAIN, cv2.FONT_HERSHEY_DUPLEX,
               cv2.FONT_HERSHEY_COMPLEX, cv2.FONT_HERSHEY_SCRIPT_SIMPLEX,
               cv2.FONT_HERSHEY_SCRIPT_COMPLEX]
HELDOUT_FONTS = [cv2.FONT_HERSHEY_TRIPLEX, cv2.FONT_HERSHEY_COMPLEX_SMALL]


def font_digit_mask(d, font, rng):
    img = np.zeros((160, 160), np.uint8)
    th = int(rng.integers(2, 7))
    scale = cv2.getFontScaleFromHeight(font, int(rng.integers(40, 70)), th)
    italic = cv2.FONT_ITALIC if rng.random() < 0.2 else 0
    cv2.putText(img, str(d), (50, 115), font | italic, scale, 255, th, cv2.LINE_AA)
    M = cv2.getRotationMatrix2D((80, 80), rng.uniform(-12, 12), 1.0)
    M[0, 1] += rng.uniform(-0.2, 0.2)
    img = cv2.warpAffine(img, M, (160, 160))
    return (img > 100).astype(np.uint8) * 255


def mnist_mask(x28):
    big = cv2.resize(x28.reshape(28, 28).astype(np.uint8), (84, 84), interpolation=cv2.INTER_CUBIC)
    return (big > 100).astype(np.uint8) * 255


def skl_mask(x8):
    big = cv2.resize((x8.reshape(8, 8) * 16).clip(0, 255).astype(np.uint8), (64, 64),
                     interpolation=cv2.INTER_CUBIC)
    return (big > 90).astype(np.uint8) * 255


def feats(masks):
    return np.array([digit_features(_to_mnist(m)) for m in masks], np.float32)


def main():
    from mlxtend.data import mnist_data
    from sklearn.datasets import load_digits
    from sklearn.linear_model import LogisticRegression

    rng = np.random.default_rng(0)
    Xm, ym = mnist_data()
    perm = rng.permutation(len(ym))
    Xm, ym = Xm[perm], ym[perm]
    sk = load_digits()
    ps = rng.permutation(len(sk.target))
    Xs, ys = sk.data[ps], sk.target[ps]

    tr_m, te_m = [mnist_mask(x) for x in Xm[:4000]], [mnist_mask(x) for x in Xm[4000:]]
    tr_s, te_s = [skl_mask(x) for x in Xs[:1400]], [skl_mask(x) for x in Xs[1400:]]
    tr_f, tr_fy = [], []
    for _ in range(40):
        for d in range(10):
            for f in TRAIN_FONTS:
                tr_f.append(font_digit_mask(d, f, rng))
                tr_fy.append(d)
    te_f, te_fy = [], []
    for _ in range(10):
        for d in range(10):
            for f in HELDOUT_FONTS:
                te_f.append(font_digit_mask(d, f, rng))
                te_fy.append(d)

    X = np.vstack([feats(tr_m), feats(tr_s), feats(tr_f)])
    y = np.concatenate([ym[:4000], ys[:1400], tr_fy])
    mu, sd = X.mean(0), X.std(0) + 1e-6
    clf = LogisticRegression(C=0.5, max_iter=3000)
    clf.fit((X - mu) / sd, y)
    for name, M, Y in [("mnist held-out", te_m, ym[4000:]), ("sklearn held-out", te_s, ys[1400:]),
                       ("held-out fonts", te_f, te_fy)]:
        acc = (clf.predict((feats(M) - mu) / sd) == np.array(Y)).mean()
        print(f"{name:18s} accuracy {acc:.3f}")
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "models", "digits_hog_softmax.npz")
    np.savez_compressed(out, W=clf.coef_.astype(np.float32), b=clf.intercept_.astype(np.float32),
                        mu=mu.astype(np.float32), sd=sd.astype(np.float32))
    print("saved", out)


if __name__ == "__main__":
    main()
