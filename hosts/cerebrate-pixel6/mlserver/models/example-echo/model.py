from mlserver import MLModel
from mlserver.types import InferenceRequest, InferenceResponse, ResponseOutput


class EchoModel(MLModel):
    async def load(self) -> bool:
        self.ready = True
        return self.ready

    async def predict(self, payload: InferenceRequest) -> InferenceResponse:
        outputs = [
            ResponseOutput(
                name=inp.name,
                shape=inp.shape,
                datatype=inp.datatype,
                data=inp.data,
            )
            for inp in payload.inputs
        ]
        return InferenceResponse(
            model_name=self.name,
            model_version=self.version,
            outputs=outputs,
        )
