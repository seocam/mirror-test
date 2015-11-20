from colab.widgets.widget_manager import WidgetManager
from colab.accounts.widgets.latest_contributions import LatestContributionsWidget

WidgetManager.register_widget('list', LatestContributionsWidget())
