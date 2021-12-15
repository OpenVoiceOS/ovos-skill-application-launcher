#!/usr/bin/env python3
from setuptools import setup

# skill_id=package_name:SkillClass
PLUGIN_ENTRY_POINT = 'mycroft-desktop-launcher.mycroftai=skill_application_launcher:ApplicationLauncherSkill'
# in this case the skill_id is defined to purposefully replace the mycroft version of the skill,
# or rather to be replaced by it in case it is present. all skill directories take precedence over plugin skills


setup(
    name='skill-application-launcher',
    version='0.0.2',
    description='OVOS application launcher skill plugin',
    url='https://github.com/JarbasSkills/skill-application-launcher',
    author='JarbasAi',
    author_email='jarbasai@mailfence.com',
    license='Apache-2.0',
    package_dir={"skill_application_launcher": ""},
    package_data={'skill_application_launcher': ["locale/*"]},
    packages=['skill_application_launcher'],
    include_package_data=True,
    install_requires=["padacioso~=0.1.1"],
    keywords='ovos skill plugin',
    entry_points={'ovos.plugin.skill': PLUGIN_ENTRY_POINT}
)
