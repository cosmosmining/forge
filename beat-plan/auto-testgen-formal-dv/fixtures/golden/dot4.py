"""Golden for the `dot4` FIXTURE (not a Forge Build 6 block)."""


def dot4(a, w, bias):
    acc = bias
    for i in range(4):
        acc += a[i] * w[i]
    cover("int32_wraps", acc > 2147483647 or acc < -2147483648)
    cover("products_cancel", acc == bias and a != [0, 0, 0, 0])
    return {"y": wrap(acc, 32)}
