from marshmallow import Schema, fields, validate, validates, validates_schema, ValidationError

CHILD_GOAL_TYPES = ["Graduation", "Post Graduation", "Marriage", "Other"]
LIFESTYLE_GOAL_TYPES = [
    "Home Purchase", "Car Purchase", "Home Renovation", "Holiday Home",
    "Foreign Tour", "Family Gifting", "Charity",
    "Child Birth Expenses", "Big Purchases", "Estate For Children", "Other"
]


class CommunicationSchema(Schema):
    mobile = fields.Str(required=True, validate=validate.Length(min=10, max=15))
    email = fields.Email(required=True)
    spouse_mobile = fields.Str(load_default=None)
    spouse_email = fields.Email(load_default=None)
    residential_address = fields.Str(load_default=None)
    consent = fields.Bool(required=True)


class PersonalSchema(Schema):
    client_name = fields.Str(required=True)
    client_occupation = fields.Str(required=True)
    client_designation = fields.Str(required=True)
    client_company = fields.Str(required=True)
    client_dob = fields.Date(required=True, format="%d/%m/%Y")
    spouse_name = fields.Str(load_default=None)
    spouse_occupation = fields.Str(load_default=None)
    spouse_designation = fields.Str(load_default=None)
    spouse_company = fields.Str(load_default=None)
    spouse_dob = fields.Date(load_default=None, format="%d/%m/%Y")
    client_retirement_age = fields.Int(load_default=60)
    spouse_retirement_age = fields.Int(load_default=55)


class ChildSchema(Schema):
    child_number = fields.Int(required=True)
    full_name = fields.Str(required=True)
    occupation = fields.Str(load_default=None)
    financially_dependent = fields.Bool(load_default=True)
    date_of_birth = fields.Date(load_default=None, format="%d/%m/%Y")


class FamilySchema(Schema):
    number_of_children = fields.Int(required=True, validate=validate.Range(min=0, max=10))
    children = fields.List(fields.Nested(ChildSchema), load_default=[])


class GoalSchema(Schema):
    category = fields.Str(required=True, validate=validate.OneOf(["child_goal", "lifestyle"]))
    goal_type = fields.Str(required=True)
    child_id = fields.UUID(load_default=None)
    target_year = fields.Int(required=True, validate=validate.Range(min=2025, max=2100))
    today_cost = fields.Float(required=True, validate=validate.Range(min=1))
    inflation_rate = fields.Float(load_default=0.06, validate=validate.Range(min=0.01, max=0.30))

    @validates_schema
    def validate_goal_type(self, data, **kwargs):
        category = data.get("category")
        goal_type = data.get("goal_type")
        if category == "child_goal" and goal_type not in CHILD_GOAL_TYPES:
            raise ValidationError(f"Must be one of {CHILD_GOAL_TYPES}", "goal_type")
        if category == "lifestyle" and goal_type not in LIFESTYLE_GOAL_TYPES:
            raise ValidationError(f"Must be one of {LIFESTYLE_GOAL_TYPES}", "goal_type")


class GoalsListSchema(Schema):
    goals = fields.List(fields.Nested(GoalSchema), required=True)


class RateUpdateSchema(Schema):
    inflation_post = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    roi_post = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    inflation_pre = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    roi_pre = fields.Float(validate=validate.Range(min=0.01, max=0.30))
