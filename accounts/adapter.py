from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """Invite only: accounts are created through /invite/<token>/ (or the admin)."""
        return False
