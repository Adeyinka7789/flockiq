from datetime import date, datetime, timedelta


class DateRangeFilter:
    DEFAULT_DAYS = 30

    def get_date_range(self, request):
        preset = request.GET.get('preset', '')
        date_from = request.GET.get('date_from', '')
        date_to = request.GET.get('date_to', '')
        today = date.today()

        if preset == 'today':
            return today, today
        elif preset == '7d':
            return today - timedelta(days=7), today
        elif preset == '30d':
            return today - timedelta(days=30), today
        elif preset == '90d':
            return today - timedelta(days=90), today
        elif preset == 'this_month':
            return today.replace(day=1), today
        elif date_from and date_to:
            try:
                return (
                    datetime.strptime(date_from, '%Y-%m-%d').date(),
                    datetime.strptime(date_to, '%Y-%m-%d').date(),
                )
            except ValueError:
                pass

        return today - timedelta(days=self.DEFAULT_DAYS), today

    def get_filter_context(self, request):
        return {
            'active_preset': request.GET.get('preset', '30d'),
            'date_from': request.GET.get('date_from', ''),
            'date_to': request.GET.get('date_to', ''),
        }
