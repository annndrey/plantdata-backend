from api import app

# gunicorn --bind localhost:5499 wsgi:app
if __name__ == "__main__":
    app.run()
    
