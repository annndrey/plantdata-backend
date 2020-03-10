import logging
import torch
import torchvision
import io
import numpy as np 

from fastapi import FastAPI
from fastapi import UploadFile
from fastapi import File
from starlette.requests import Request
from torchvision import datasets, models, transforms
from collections import OrderedDict
from PIL import Image
from imgaug import augmenters as iaa 


#MODEL = "/home/annndrey/cityfarmer/cityfarm_56cl_50_acc948.md"
MODEL = "/home/annndrey/cityfarmer/cityfarm_56cl_50_acc952_100320.md"
USING_MODEL_NAME = 'densenet169'
NUM_CLASSES_USED = 41
RESIZE = 224

logger = logging.getLogger("api")
app = FastAPI(redoc_url=None, docs_url=None)


class ImgResizeAndPad:
    #max_cropped_part - maximum percentage of each side length cropped (with probability ~0.5)
#max_ratio_change - maximum relative increase of the short side toward square size (with probability 0.5). Set it to 1 to keep the aspect ratio of the img always.
    def __init__(self, resize=224, max_ratio_change = 1.2):
        self.max_ratio_change = max_ratio_change
        self.resize = resize
        self.pad = iaa.size.PadToFixedSize(width = resize, height = resize, pad_mode='constant', pad_cval=0, position='center')
    def __call__(self, img):
        img = np.array(img)
        (h,w) = img.shape[0:2]
        keep_h=False
        M = w
        m = h
        if h>w :
            keep_h=True
            M = h
            m = w
        if self.max_ratio_change > 1:
            new_m = int(m*self.max_ratio_change*self.resize/M)
            if new_m>self.resize: new_m=self.resize
        else:
            new_m = int(m*self.resize/M)
        if keep_h:
            resize_to_square = iaa.Resize({"height": self.resize, "width": new_m})
        else:
            resize_to_square = iaa.Resize({"height": new_m, "width": self.resize})
        img = resize_to_square.augment_image( img )
        img = self.pad.augment_image( img )
        return img


only_make_square_transform = transforms.Compose([
    ImgResizeAndPad(resize=RESIZE),
    lambda x: Image.fromarray(x),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]) ])


def get_model_results(model, results, img):
    idx_to_class = {v: k for k, v in model.class_to_idx.items()}
    outputs = model(img)
    _, preds = torch.max(outputs, 1)
    detected_img_type = idx_to_class[int(preds)]
    return detected_img_type



def load_model(file_name):
    checkpoint = torch.load(file_name, map_location='cpu')
    if 'state_dict' in checkpoint:
        state_dict = checkpoint['state_dict']
    else:
        state_dict = checkpoint
    arch = checkpoint['arch']
    class_to_idx = checkpoint['class_to_idx']
    num_classes = len(class_to_idx)
    model = torchvision.models.__dict__[arch](num_classes=num_classes)
    model_dict = model.state_dict()
    new_state_dict = OrderedDict()
    matched_layers, discarded_layers = [], []
    for k, v in state_dict.items():
        if k.startswith('module.'):
            k = k[7:]
        if k in model_dict and model_dict[k].size() == v.size():
            new_state_dict[k] = v
            matched_layers.append(k)
        else:
            discarded_layers.append(k)
    model_dict.update(new_state_dict)
    model.load_state_dict(model_dict)
    model.class_to_idx = class_to_idx

    return model


@app.on_event("startup")
async def startup_event():
    global aimodel
    aimodel = ""
    trained_model = load_model(MODEL)
    trained_model.eval()
    aimodel = trained_model
    print(MODEL)

    
@app.post("/loadimage")
async def create_upload_file(request: Request):
    form = await request.form()
    imagefile = form["imagefile"].filename
    contents = await form["imagefile"].read()

    img_pil = Image.open(io.BytesIO(contents))
    img_tensor = only_make_square_transform(img_pil)
    img_tensor.unsqueeze_(0)
    img_variable = img_tensor
    result = {}
    result = get_model_results(aimodel, result, img_variable)
    
    return {"filename": imagefile, "length": len(contents), 'objtype': result}
