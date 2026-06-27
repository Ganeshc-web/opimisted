from flask_restx import fields

error_model = None


def init_swagger_models(api):
    global error_model

    error_model = api.model("ErrorResponse", {
        "status": fields.String(
            required=True,
            description="Response status for failed requests.",
            example="error",
        ),
        "code": fields.String(
            required=True,
            description="Machine-readable error code.",
            example="INVALID_INPUT",
        ),
        "message": fields.String(
            required=True,
            description="Human-readable explanation of the failure.",
            example="years_to_retirement must be between 1 and 60.",
        ),
        "field": fields.String(
            required=False,
            description="Input field associated with the error, if applicable.",
            example="years_to_retirement",
        ),
        "request_id": fields.String(
            required=True,
            description="Unique request identifier for tracing support issues.",
            example="f47ac10b-58cc-4372-a567-0e02b2c3d479",
        ),
    })

    return error_model
