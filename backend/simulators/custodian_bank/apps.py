from django.apps import AppConfig


class CustodianBankSimulatorConfig(AppConfig):
    name = "simulators.custodian_bank"
    label = "simulator"
    verbose_name = "Simulated custodian bank (tests and demos only)"
