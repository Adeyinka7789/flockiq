import urllib.request

files = {
    'static/js/htmx.min.js': 'https://unpkg.com/htmx.org@1.9.10/dist/htmx.min.js',
    'static/js/alpine.min.js': 'https://unpkg.com/alpinejs@3.13.3/dist/cdn.min.js',
    'static/js/chart.min.js': 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js',
}

for path, url in files.items():
    urllib.request.urlretrieve(url, path)
    print(f'Downloaded {path}')
