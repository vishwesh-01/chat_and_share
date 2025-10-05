from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, join_room, leave_room, emit
import time
import uuid
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['MAX_CONTENT_LENGTH'] = 48 * 1024 * 1024  # 48MB max upload
socketio = SocketIO(app)

# In-memory storage for rooms and messages
rooms = {}
room_messages = {}
# Keep track of users who have left to avoid duplicate messages
left_users = set()

# Allowed file extensions
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'mp4', 'mp3'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat')
def chat():
    if 'username' not in session or 'room' not in session:
        return redirect(url_for('index'))
    
    room = session['room']
    if room not in rooms:
        return redirect(url_for('index'))
    
    return render_template('chat.html', username=session['username'], room=room, room_name=rooms[room]['name'])

@app.route('/join', methods=['POST'])
def join():
    username = request.form.get('username')
    room = request.form.get('room')
    create_new = request.form.get('create_new') == 'true'
    room_name = request.form.get('room_name', room)  # Default to room code if no name provided
    
    if not username or not room:
        return jsonify({"error": "Username and room code are required"}), 400
    
    if create_new:
        if room in rooms:
            return jsonify({"error": "Room already exists. Try a different code."}), 400
        rooms[room] = {
            'users': [], 
            'created_at': time.time(), 
            'name': room_name
        }
        room_messages[room] = []
    elif room not in rooms:
        return jsonify({"error": "Room doesn't exist"}), 404
    
    session['username'] = username
    session['room'] = room
    
    # Remove from left_users if rejoining
    user_room_key = f"{username}:{room}"
    if user_room_key in left_users:
        left_users.remove(user_room_key)
        
    return jsonify({"success": True, "redirect": url_for('chat')})

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        # Read file content into memory
        file_content = file.read()
        # Encode file content to base64
        file_base64 = base64.b64encode(file_content).decode('utf-8')
        
        # Get the file extension for determining file type
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        file_type = 'image' if file_ext in ['png', 'jpg', 'jpeg', 'gif'] else 'document'
        
        # Create a data URL for images or a generic file object for documents
        if file_type == 'image':
            file_url = f"data:image/{file_ext};base64,{file_base64}"
        else:
            file_url = f"data:application/{file_ext};base64,{file_base64}"
        
        return jsonify({
            "success": True,
            "filename": file.filename,
            "original_name": file.filename,
            "file_type": file_type,
            "file_url": file_url
        })
    
    return jsonify({"error": "File type not allowed"}), 400

@socketio.on('join_room')
def handle_join_room(data):
    room = session.get('room')
    username = session.get('username')
    
    if not room or not username:
        return
    
    join_room(room)
    
    if username not in rooms[room]['users']:
        rooms[room]['users'].append(username)
    
    # Send join notification to room
    emit('user_join', {
        'username': username, 
        'users': rooms[room]['users'],
        'room_name': rooms[room]['name']
    }, room=room)
    
    # Send message history to the new user
    if room in room_messages:
        emit('message_history', {'messages': room_messages[room]})

@socketio.on('leave_room')
def handle_leave_room():
    room = session.get('room')
    username = session.get('username')
    
    if not room or not username:
        return
    
    leave_room(room)
    
    # Create unique key for this user and room
    user_room_key = f"{username}:{room}"
    
    if room in rooms and username in rooms[room]['users']:
        rooms[room]['users'].remove(username)
        
        # Only notify if this is the first time user left
        if user_room_key not in left_users:
            left_users.add(user_room_key)
            # Notify others that user has left (only once)
            emit('user_leave', {
                'username': username, 
                'users': rooms[room]['users']
            }, room=room)
    
    # If room is empty, clean it up
    if room in rooms and not rooms[room]['users']:
        del rooms[room]
        if room in room_messages:
            del room_messages[room]

@socketio.on('message')
def handle_message(data):
    room = session.get('room')
    username = session.get('username')
    
    if not room or not username:
        return
    
    message_data = {
        'username': username,
        'message': data.get('message'),
        'file': data.get('file'),
        'timestamp': time.time()
    }
    
    # Store the message
    if room not in room_messages:
        room_messages[room] = []
    room_messages[room].append(message_data)
    
    # Send to everyone in the room
    emit('message', message_data, room=room)

@socketio.on('update_room_info')
def handle_update_room_info(data):
    room = session.get('room')
    
    if not room or room not in rooms:
        return
    
    # Update room name if provided
    if 'room_name' in data:
        rooms[room]['name'] = data['room_name']
        
    # Notify everyone in the room about the update
    emit('room_updated', {
        'room_name': rooms[room]['name']
    }, room=room)

@socketio.on('disconnect')
def handle_disconnect():
    handle_leave_room()

# if __name__ == '__main__':
#     socketio.run(app, debug=True, host='0.0.0.0', port = 5000)
if __name__ == '__main__':
     socketio.run(app)
