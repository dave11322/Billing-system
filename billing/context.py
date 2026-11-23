from .models import role_of


def user_role(request):
    user = request.user
    return {"role": role_of(user) if user.is_authenticated else None}
