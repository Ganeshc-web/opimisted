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
    # Preferred field; full_name kept as legacy alias.
    child_name = fields.Str(load_default=None)
    full_name = fields.Str(load_default=None)
    occupation = fields.Str(load_default=None)
    financially_dependent = fields.Bool(load_default=True)
    date_of_birth = fields.Date(load_default=None, format="%d/%m/%Y")

    @validates_schema
    def require_child_name(self, data, **kwargs):
        name = (data.get("child_name") or data.get("full_name") or "").strip()
        if not name:
            raise ValidationError(
                "child_name is required (full_name also accepted).",
                field_name="child_name",
            )
        data["child_name"] = name
        data["full_name"] = name


class FamilySchema(Schema):
    number_of_children = fields.Int(required=True, validate=validate.Range(min=0))
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
    # Required when goal_type is Other — saved into goal_type as the custom name.
    goal_name = fields.Str(load_default=None)
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
        goal_type = (data.get("goal_type") or "").strip()
        goal_name = (data.get("goal_name") or "").strip()
        allowed = CHILD_GOAL_TYPES if category == "child_goal" else LIFESTYLE_GOAL_TYPES

        if goal_type == "Other":
            if not goal_name:
                raise ValidationError(
                    "goal_name is required when goal_type is Other.",
                    "goal_name",
                )
            if len(goal_name) > 100:
                raise ValidationError(
                    "goal_name must be at most 100 characters.",
                    "goal_name",
                )
            # Persist the custom name as goal_type for reports/PDF.
            data["goal_type"] = goal_name
        elif goal_type in allowed:
            data["goal_type"] = goal_type
        elif goal_type:
            # Re-submit / free-text custom name already stored as goal_type.
            if len(goal_type) > 100:
                raise ValidationError(
                    "goal_type must be at most 100 characters.",
                    "goal_type",
                )
            data["goal_type"] = goal_type
        else:
            raise ValidationError(
                f"Must be one of {allowed}, or Other with goal_name.",
                "goal_type",
            )

        data.pop("goal_name", None)


class GoalsListSchema(Schema):
    # Empty goals allowed — clients may skip Flow 4 / submit no goals.
    goals = fields.List(fields.Nested(GoalSchema), load_default=list)


class RateUpdateSchema(Schema):
    inflation_post = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    roi_post = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    inflation_pre = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    roi_pre = fields.Float(validate=validate.Range(min=0.01, max=0.30))
    pf_growth = fields.Float(validate=validate.Range(min=0.0, max=0.30))


class ApiKeyCreateSchema(Schema):
    client_name = fields.Str(required=True, validate=validate.Length(min=1, max=120))
    role = fields.Str(load_default="user", validate=validate.OneOf(["user", "admin"]))
    expires_at = fields.DateTime(load_default=None)


class TestimonialSchema(Schema):
    client_name = fields.Str(required=True, validate=validate.Length(min=1, max=120))
    review_message = fields.Str(required=True, validate=validate.Length(min=1, max=5000))
    avatar_url = fields.Str(load_default=None, validate=validate.Length(max=500))
    is_visible = fields.Bool(load_default=False)
    sort_order = fields.Int(load_default=0, validate=validate.Range(min=0, max=9999))

    @validates("client_name")
    def validate_client_name(self, value, **kwargs):
        if not value or not value.strip():
            raise ValidationError("client_name cannot be blank or whitespace.")

    @validates("review_message")
    def validate_review_message(self, value, **kwargs):
        if not value or not value.strip():
            raise ValidationError("review_message cannot be blank or whitespace.")


class TestimonialUpdateSchema(Schema):
    client_name = fields.Str(validate=validate.Length(min=1, max=120))
    review_message = fields.Str(validate=validate.Length(min=1, max=5000))
    avatar_url = fields.Str(validate=validate.Length(max=500), allow_none=True)
    is_visible = fields.Bool()
    sort_order = fields.Int(validate=validate.Range(min=0, max=9999))

    @validates("client_name")
    def validate_client_name(self, value, **kwargs):
        if value is not None and not value.strip():
            raise ValidationError("client_name cannot be blank or whitespace.")

    @validates("review_message")
    def validate_review_message(self, value, **kwargs):
        if value is not None and not value.strip():
            raise ValidationError("review_message cannot be blank or whitespace.")


class ServiceSchema(Schema):
    title = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    description = fields.Str(required=True, validate=validate.Length(min=1, max=10000))
    icon_url = fields.Str(load_default=None, validate=validate.Length(max=500))
    is_visible = fields.Bool(load_default=True)
    sort_order = fields.Int(load_default=0, validate=validate.Range(min=0, max=9999))

    @validates("title")
    def validate_title(self, value, **kwargs):
        if not value or not value.strip():
            raise ValidationError("title cannot be blank or whitespace.")

    @validates("description")
    def validate_description(self, value, **kwargs):
        if not value or not value.strip():
            raise ValidationError("description cannot be blank or whitespace.")


class ServiceUpdateSchema(Schema):
    title = fields.Str(validate=validate.Length(min=1, max=200))
    description = fields.Str(validate=validate.Length(min=1, max=10000))
    icon_url = fields.Str(validate=validate.Length(max=500), allow_none=True)
    is_visible = fields.Bool()
    sort_order = fields.Int(validate=validate.Range(min=0, max=9999))

    @validates("title")
    def validate_title(self, value, **kwargs):
        if value is not None and not value.strip():
            raise ValidationError("title cannot be blank or whitespace.")

    @validates("description")
    def validate_description(self, value, **kwargs):
        if value is not None and not value.strip():
            raise ValidationError("description cannot be blank or whitespace.")


class GetInTouchSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=120))
    email = fields.Email(required=True)
    mobile = fields.Str(required=True, validate=validate.Length(min=10, max=15))
    message = fields.Str(load_default=None)

    @validates("mobile")
    def validate_mobile(self, value, **kwargs):
        if not value.isdigit():
            raise ValidationError("Mobile number must contain only digits.")

    @validates("name")
    def validate_name(self, value, **kwargs):
        if not value or not value.strip():
            raise ValidationError("name cannot be blank or whitespace.")
