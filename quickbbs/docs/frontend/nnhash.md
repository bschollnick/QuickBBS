# Nnhash

> Auto-generated documentation for [frontend.nnhash](blob/master/frontend/nnhash.py) module.

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Nnhash

#### Attributes

- `session` - Load ONNX model: `onnxruntime.InferenceSession(sys.argv[1])`
- `seed1` - Load output hash matrix: `open(sys.argv[2], 'rb').read()[128:]`
- `image` - Preprocess image: `Image.open(sys.argv[3]).convert('RGB')`
- `inputs` - Run model: `{session.get_inputs()[0].name: arr}`
- `hash_output` - Convert model output to hex hash: `seed1.dot(outs[0].flatten())`
