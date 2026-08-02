from tests.tests import app

from chanina.core.bootstrapper import Bootstrapper


# Example workflow
workflow = {
    "steps": [
        {
            "identifier": "login",
            "args": {
                "username": "Léonard",
                "password": "monsupermotdepasse"
            },
            "flow_type": "chain",
        },
        {
            "identifier": "check_profile",
            "flow_type": "chain",
        },
    ],
    "instances": {
        "check_profile": [
            {
                "args": {
                    "profile_link": "https://www.instagram.com/p/DPj1_81DX-L"
                },
            },
            {
                "args": {
                    "profile_link": "https://www.instagram.com/p/DOvfMdhCIaz"
                },
            },
            {
                "args": {
                    "profile_link": "https://www.instagram.com/p/DLcxIczNg1y"
                },
            }

        ]
    }
}


def run():
    bootstrapper = Bootstrapper(app.features, workflow)
    bootstrapper.build()
