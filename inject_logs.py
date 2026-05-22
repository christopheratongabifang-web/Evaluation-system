import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

injections = [
    (r"(@app\.route\('/register'[\s\S]*?db\.session\.commit\(\))", r"\1\n        log_action('User Registration', f'New user registered: {username}')"),
    (r"(@app\.route\('/student/profile'[\s\S]*?db\.session\.commit\(\))", r"\1\n        log_action('Profile Updated', 'Student updated their profile')"),
    (r"(@app\.route\('/admin/send_notification'[\s\S]*?db\.session\.commit\(\))", r"\1\n        log_action('Broadcast Sent', f'Message: {message}')"),
    (r"(@app\.route\('/admin/delete_notification/<int:notification_id>'[\s\S]*?db\.session\.commit\(\))", r"\1\n    log_action('Broadcast Deleted', 'A broadcast message was deleted')"),
    (r"(@app\.route\('/send_message/<int:recipient_id>'[\s\S]*?db\.session\.commit\(\))", r"\1\n        log_action('Message Sent', 'A direct message was sent')"),
    (r"(@app\.route\('/delete_message/<int:msg_id>'[\s\S]*?db\.session\.commit\(\))", r"\1\n        log_action('Message Deleted', 'A direct message was deleted')"),
    (r"(@app\.route\('/clear_conversation/<int:student_id>'[\s\S]*?db\.session\.commit\(\))", r"\1\n    log_action('Conversation Cleared', f'Cleared conversation with student ID {student_id}')"),
    (r"(@app\.route\('/clear_all_messages'[\s\S]*?db\.session\.commit\(\))", r"\1\n    log_action('All Messages Cleared', 'Admin cleared all messages and broadcasts')"),
    (r"(@app\.route\('/add_category'[\s\S]*?db\.session\.commit\(\))", r"\1\n        log_action('Category Added', 'Added new book category')"),
    (r"(@app\.route\('/delete_category/<int:category_id>'[\s\S]*?db\.session\.commit\(\))", r"\1\n    log_action('Category Deleted', 'A book category was deleted')"),
    (r"(@app\.route\('/admin/evaluations/<int:evaluation_id>/edit'[\s\S]*?db\.session\.commit\(\))", r"\1\n        log_action('Evaluation Edited', f'Edited evaluation: {evaluation.title}')"),
    (r"(@app\.route\('/admin/evaluations/<int:evaluation_id>/delete'[\s\S]*?db\.session\.commit\(\))", r"\1\n    log_action('Evaluation Deleted', 'An evaluation was deleted')"),
    (r"(@app\.route\('/admin/assignments/<int:assignment_id>/edit'[\s\S]*?db\.session\.commit\(\))", r"\1\n        log_action('Assignment Edited', f'Edited assignment: {assignment.title}')"),
    (r"(@app\.route\('/admin/assignments/<int:assignment_id>/delete'[\s\S]*?db\.session\.commit\(\))", r"\1\n    log_action('Assignment Deleted', 'An assignment was deleted')"),
    (r"(@app\.route\('/admin/assignments/grade/<int:submission_id>'[\s\S]*?db\.session\.commit\(\))", r"\1\n    log_action('Submission Graded', f'Graded submission with score: {grade}%')")
]

for pattern, replacement in injections:
    content = re.sub(pattern, replacement, content, count=1)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Injections complete")
