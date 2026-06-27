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

    @validates("mobile")
    def validate_mobile(self, value, **kwargs):
        if not value.isdigit():
            raise ValidationError("Mobile number must contain only digits.")
        if len(value) < 10 or len(value) > 15:
            raise ValidationError("Mobile number must be 10-15 digits.")


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

    @validates("client_name")
    def validate_client_name(self, value, **kwargs):
        if not value or not value.strip():
            raise ValidationError("client_name cannot be blank or whitespace.")

    @validates("spouse_name")
    def validate_spouse_name(self, value, **kwargs):
        if value is not None and not value.strip():
            raise ValidationError("spouse_name cannot be blank or whitespace.")

    @validates("client_dob")
    def validate_client_dob(self, value, **kwargs):
        from datetime import date

        today = date.today()
        if value > today:
            raise ValidationError("Date of birth cannot be in the future.")
        age = today.year - value.year
        if age > 100:
            raise ValidationError("Age cannot exceed 100 years.")
        if age < 18:
            raise ValidationError("Age must be at least 18 years.")

    @validates("spouse_dob")
    def validate_spouse_dob(self, value, **kwargs):
        from datetime import date

        if value is None:
            return
        today = date.today()
        if value > today:
            raise ValidationError("Date of birth cannot be in the future.")
        age = today.year - value.year
        if age > 100:
            raise ValidationError("Age cannot exceed 100 years.")
        if age < 18:
            raise ValidationError("Age must be at least 18 years.")

    @validates_schema
    def validate_retirement_ages(self, data, **kwargs):
        client_dob = data.get("client_dob")
        client_ret_age = data.get("client_retirement_age")

        if client_dob and client_ret_age:
            from datetime import date

            client_age = date.today().year - client_dob.year
            if client_ret_age <= client_age:
                raise ValidationError(
                    "client_retirement_age must be greater than current age.",
                    field_name="client_retirement_age"
                )

        spouse_dob = data.get("spouse_dob")
        spouse_ret_age = data.get("spouse_retirement_age")

        if spouse_dob and spouse_ret_age:
            from datetime import date

            spouse_age = date.today().year - spouse_dob.year
            if spouse_ret_age <= spouse_age:
                raise ValidationError(
                    "spouse_retirement_age must be greater than current age.",
                    field_name="spouse_retirement_age"
                )


class ChildSchema(Schema):
    child_number = fields.Int(required=True)
    full_name = fields.Str(required=True)
    occupation = fields.Str(load_default=None)
    financially_dependent = fields.Bool(load_default=True)
    date_of_birth = fields.Date(load_default=None, format="%d/%m/%Y")


class FamilySchema(Schema):
    number_of_children = fields.Int(required=True, validate=validate.Range(min=0, max=10))
    children = fields.List(fields.Nested(ChildSchema), load_default=[])

    @validates_schema
    def validate_children_count(self, data, **kwargs):
        n = data.get("number_of_children", 0)
        children = data.get("children", [])
        if n > 0 and len(children) == 0:
            raise ValidationError(
                "children list cannot be empty when number_of_children > 0",
                field_name="children"
            )
        if len(children) != n:
            raise ValidationError(
                "children list length must match number_of_children",
                field_name="children"
            )


class GoalSchema(Schema):
    category = fields.Str(required=True, validate=validate.OneOf(["child_goal", "lifestyle"]))
    goal_type = fields.Str(required=True)
    child_id = fields.UUID(load_default=None)
    education_program_id = fields.UUID(load_default=None)
    tour_destination_id = fields.UUID(load_default=None)
    target_year = fields.Int(required=True, validate=validate.Range(min=2025, max=2100))
    today_cost = fields.Float(load_default=None, validate=validate.Range(min=1))
    inflation_rate = fields.Float(load_default=None, validate=validate.Range(min=0.01, max=0.30))

    @validates("target_year")
    def validate_target_year(self, value, **kwargs):
        from datetime import date

        if value <= date.today().year:
            raise ValidationError("target_year must be in the future.")

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

    @validates("goals")
    def validate_goals_not_empty(self, value, **kwargs):
        if len(value) == 0:
            raise ValidationError("At least one goal is required.")


class RateUpdateSchema(Schema):
    inflation_post = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    roi_post = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    inflation_pre = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    roi_pre = fields.Float(validate=validate.Range(min=0.01, max=0.30))
