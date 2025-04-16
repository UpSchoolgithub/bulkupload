from flask import Flask, request, jsonify, send_file
import os
import requests
import json
import time
import pandas as pd
import re
import openai
from flask_cors import CORS
import tempfile

# Mathpix API credentials
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MATHPIX_API_KEY = os.getenv("MATHPIX_API_KEY")
MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID")

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

openai.api_key = OPENAI_API_KEY

# List of Question Categories
question_categories = [ 
    "Answer the following correctly", "Evaluate the following", "Simplify the following expr.", "Choose the ODD one Out",
    "Numerical/application based", "Very Short Answer Questions", "True or False", "CBQ with sub questions", "LAT with sub questions",
    "LAT Questions", "SAT Questions (3 Marks)", "SAT Questions (2 Marks)", "Dialogues completion", "Sentence completion", "Rearrange the following words",
    "Identifying the following", "Sentence Transformation", "Sentence reordering", "Editing and Omission", "Error correction", "Joining Sentences", "Fill in the Blanks",
    "Passage based questions", "Composition writing", "Short Answer Type (3 marks)", "Short Answer Type (2 marks)", "Extract based question", "Choose the correct answers", 
    "Locating and Plotting on map", "Extract based on Map Survey", "Assertion & Reasons Type",
    "Mark Questions", "2 Marks Question", "5 Mark Question", "4 Mark Question", "3 Mark Question", "1 Mark Question", "Match the following Questions",
    "Multiple Choice Question", "Describe Questions", "Direct Question"
 ]

def poll_status(pdf_id, headers, poll_interval=13, max_polls=10):
    url = f"https://api.mathpix.com/v3/pdf/{pdf_id}.json"
    for poll_count in range(max_polls):
        print(f"Polling attempt {poll_count + 1} for PDF ID {pdf_id}")
        response = requests.get(url, headers=headers)
        status_data = response.json()
        print("Polling Status:", status_data)
        if status_data.get("status") == "completed":
            return status_data
        time.sleep(poll_interval)
    return None

def process_with_mathpix(file):
    options = {
        "conversion_formats": {"docx": True, "tex.zip": True},
        "math_inline_delimiters": ["$", "$"],
        "rm_spaces": True
    }

    r = requests.post("https://api.mathpix.com/v3/pdf",
        headers={
            "app_id": MATHPIX_APP_ID,
            "app_key": MATHPIX_API_KEY
        },
        data={
            "options_json": json.dumps(options)
        },
        files={
            "file": (file.filename, file.stream, file.content_type)
        }
    )

    API_resp = r.json()
    pdf_id = API_resp.get("pdf_id")
    if not pdf_id:
        return None

    headers = {
        "app_key": MATHPIX_API_KEY,
        "app_id": MATHPIX_APP_ID
    }

    status_data = poll_status(pdf_id, headers)
    if not status_data:
        return None

    url = f"https://api.mathpix.com/v3/pdf/{pdf_id}.mmd"
    response = requests.get(url, headers=headers)
    mmd_content = response.text

    mmd_content = mmd_content.replace("{", "").replace("}", "").replace(r"\section*", "").replace(r"$\qquad$", "__")
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    temp_file.write(mmd_content.encode('utf-8'))
    temp_file.close()

    return temp_file.name

def parse_questions(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    questions = []
    lines = content.split('\n')
    current_question = ""
    question_number = 1
    
    for line in lines:
        if line.strip():
            if re.match(r'^\(?\s*([0-9]+)\s*[\).]', line, re.IGNORECASE):
                if current_question:
                    questions.append({
                        'text': current_question.strip(),
                        'number': question_number
                    })
                    question_number += 1
                current_question = line.strip()
            else:
                current_question += "\n" + line.strip()
    
    if current_question:
        questions.append({
            'text': current_question.strip(),
            'number': question_number
        })
    
    return questions

def parse_solutions(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    
    solutions = []
    lines = content.split('\n')
    current_solution = ""
    solution_number = 1
    
    for line in lines:
        if line.strip():
            if re.match(r'^\(?\s*([0-9]+)\s*[\).]', line, re.IGNORECASE):
                if current_solution:
                    solutions.append({
                        'text': current_solution.strip(),
                        'number': solution_number
                    })
                    solution_number += 1
                current_solution = line.strip()
            else:
                current_solution += "\n" + line.strip()
    
    if current_solution:
        solutions.append({
            'text': current_solution.strip(),
            'number': solution_number
        })
    
    return solutions

# Function to process descriptive questions
def process_descriptive_questions(questions, solutions):
    descriptive_data = []
    solution_dict = {sol['number']: sol['text'] for sol in solutions}

    for question in questions:
        solution = solution_dict.get(question['number'], '')
        question_text = question['text'].strip()
        question_text = question_text.replace('\n', ' ')
        
        if (not re.findall(r'[a-dA-D][).] [^\n]+', question_text)  # Checks for A. or a)
            and not re.search(r'_{2,}', question_text)):
            descriptive_data.append({
                'Question Label': f'Q{question["number"]}',
                'Question Category': 'Descriptive',
                'Cognitive Skills': '',
                'Question Source': '',
                'Question Appears in': 'Pre/Post-Worksheet/Test',
                'Level of Difficulty': '',
                'Question': question_text.strip(),
                'Marks': 1,
                'Display Answer': solution.strip(),
                'Answer Type': '',
                'Answer Weightage': '',
                'Answer Content': '',  
                'Answer Explanation': solution.strip()  
            })
    
    return descriptive_data

# Function to process objective questions
def process_objective_questions(questions, solutions):
    objective_data = []
    solution_dict = {sol['number']: sol['text'] for sol in solutions}

    for question in questions:
        solution = solution_dict.get(question['number'], '')
        question_text = re.sub(r'[a-dA-D][).] [^\n]+', '', question['text']).strip()
        options = re.findall(r'[a-dA-D][).] [^\n]+', question['text'])

        if len(options) == 4:
            objective_data.append({
                'Question Label': f'Q{question["number"]}',
                'Question Category': '',
                'Cognitive Skills': '',
                'Question Source': '',
                'Question Appears in': 'Pre/Post-Worksheet/Test',
                'Level of Difficulty': '',
                'Question': question_text,
                'Marks': 1,
                'Answer Type1': 'Words', 
                'Answer Content1': options[0] if len(options) > 0 else '',
                'Correct Answer1': 'No',
                'Answer Weightage1': 0,
                'Answer Type2': 'Words',  
                'Answer Content2': options[1] if len(options) > 1 else '',
                'Correct Answer2': 'No',
                'Answer Weightage2': 0,
                'Answer Type3': 'Words',  
                'Answer Content3': options[2] if len(options) > 2 else '',
                'Correct Answer3': 'No',
                'Answer Weightage3': 0,
                'Answer Type4': 'Words',  
                'Answer Content4': options[3] if len(options) > 3 else '',
                'Correct Answer4': 'No',
                'Answer Weightage4': 0,
                'Answer Explanation': solution
            })
    
    return objective_data

# Function to process subjective questions
def process_subjective_questions(questions, solutions):
    subjective_data = []
    solution_dict = {sol['number']: sol['text'] for sol in solutions}

    for question in questions:
        question_text = re.sub(r'[a-d][A-D]\) [^\n]+', '', question['text']).strip()
        solution = solution_dict.get(question['number'], '')
        
        if re.search(r'_{2,}', question_text): 
            subjective_data.append({
                'Question Label': f'Q{question["number"]}',
                'Question Category': 'Fill in the Blanks',
                'Cognitive Skills': '',
                'Question Source': '',
                'Question Appears in': 'Pre/Post-Worksheet/Test',
                'Level of Difficulty': '',
                'Question': question_text,
                'Marks': 1,
                'Answer Type': ' ',  
                'Answer': '',  
                'Answer Display': 'yes',  
                'Weightage': 1,  
                'Placeholder': '',  
                'answer_explanation': solution if solution else '' 
            })
    
    return subjective_data

def extract_correct_answer(explanation):
    if not explanation or not isinstance(explanation, str):
        return None
    
    match = re.search(r'[\(\s]([a-dA-D])[\).\s]', explanation, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None

def mark_correct_answers(objective_df):
    for index, row in objective_df.iterrows():
        correct_answer = extract_correct_answer(row['Answer Explanation'])
        
        for i in range(1, 5):
            answer_content = row[f'Answer Content{i}']
            if pd.isna(answer_content):
                objective_df.at[index, f'Correct Answer{i}'] = 'No'
                objective_df.at[index, f'Answer Weightage{i}'] = 0
            elif correct_answer and answer_content.startswith(f"{correct_answer})"):
                objective_df.at[index, f'Correct Answer{i}'] = 'Yes'
                objective_df.at[index, f'Answer Weightage{i}'] = row['Marks'] if not pd.isna(row['Marks']) else 0
            else:
                objective_df.at[index, f'Correct Answer{i}'] = 'No'
                objective_df.at[index, f'Answer Weightage{i}'] = 0
    
    return objective_df


# Function to process files to Excel
def process_files_to_excel(questions_file, solutions_file, output_excel_path):
    questions = parse_questions(questions_file)
    solutions = parse_solutions(solutions_file)
    
    objective_data = process_objective_questions(questions, solutions)
    subjective_data = process_subjective_questions(questions, solutions)
    descriptive_data = process_descriptive_questions(questions, solutions)
    
    objective_df = pd.DataFrame(objective_data)
    subjective_df = pd.DataFrame(subjective_data)
    descriptive_df = pd.DataFrame(descriptive_data)
    
    objective_df = mark_correct_answers(objective_df)
    
    with pd.ExcelWriter(output_excel_path, engine='openpyxl') as writer:
        objective_df.to_excel(writer, sheet_name='Objective', index=False)
        subjective_df.to_excel(writer, sheet_name='Subjective', index=False)
        descriptive_df.to_excel(writer, sheet_name='Descriptive', index=False)
    
    print(f"Excel file created successfully at: {output_excel_path}")

def get_objective_details(question_content):
    prompt = f"""
    Based on the following question content, provide the following details:
    1. Question Category: {question_categories}  please select any one of this
    2. Cognitive Skills: [Remembering, Understanding, Applying, Analysing, Evaluating, Creating]
    3. Question Source: UpSchool DB
    4. Level of Difficulty: Less/Moderate/Highly
    5. Marks: 1
    6. Answer Type: Words/Numbers/Equation/Alpha Numeric please select any one of these.

    Question Content: {question_content}
    """
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that categorizes questions."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=150
    )
    
    return response.choices[0].message['content'].strip()

# Function to get details for Subjective questions
def get_subjective_details(question_content):
    prompt = f"""
    Based on the following question content, provide the following details:
    1. Question Category: {question_categories} from the provided list
    2. Cognitive Skills (Remembering, Understanding, Applying, Analysing, Evaluating, Creating) please select any one of these only
    3. Question Source (UpSchool DB)
    4. Level of Difficulty ('Less' - Remembering, Understanding (simple), 'Moderate'- Understanding (complex), Applying (simple), Creating (Simple) 'High' - Applying (complex), Analysing, Evaluating, Creating (Complex). Just give the response as 'Less', 'Moderate' or 'High' only.)
    5. Marks (1, 2, 3, 4, 5, 6... as given in the question paper within brackets)
    6. Answer Type (Words,Numbers,Equation) Please select any one of these
    7. Answer Content: (Understanding the question and answer explanation generate a detailed marking scheme based on the answer allotted to it. 
       Break the answer into specific logical or conceptual steps/ pointers based on what is actually written in the solution. 
       Each step/ point should include a brief description and the marks awarded. The marking scheme should be context-specific, 
       not generic, and should allow for variations in variable names, wording, or approach as long as the logic is correct. Avoid verification step in the rubrics. 
       Give the output points in a single line and not as bullet points.)

    Question Categories:
    {", ".join(question_categories)}

    Question Content: {question_content}
    """
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that categorizes questions and provides additional details."},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=1500
    )
    
    return response.choices[0].message['content'].strip()

def get_descriptive_details(question_content):
    prompt = f"""
    Based on the following question content, provide the following details:
    1. Question Category {question_categories} select from the provided list
    2. Cognitive Skills (Remembering, Understanding, Applying, Analysing, Evaluating, Creating) please select any one of these only
    3. Question Source (UpSchool DB)
    4. Level of Difficulty ('Less' - Remembering, Understanding (simple), 'Moderate'- Understanding (complex), Applying (simple), Creating (Simple) 'High' - Applying (complex), Analysing, Evaluating, Creating (Complex). Just give the response as 'Less', 'Moderate' or 'High' only.)
    5. Marks (1, 2, 3, 4, 5, 6... as given in the question paper within brackets)
    6. Answer Type (Equation, Phrases) Please select any one of these
    7. Answer Content: (Understanding the question and answer explanation generate a detailed marking scheme based on the answer allotted to it. 
       Break the answer into specific logical or conceptual steps/ pointers based on what is actually written in the solution. 
       Each step/ point should include a brief description and the marks awarded. The marking scheme should be context-specific, 
       not generic, and should allow for variations in variable names, wording, or approach as long as the logic is correct. Avoid verification step in the rubrics. 
       Give the output points in a single line and not as bullet points.)

    Question Content: {question_content}
    """
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful assistant that categorizes questions."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=300
    )

    return response.choices[0].message['content'].strip()

def process_excel_file_with_gpt(input_path, output_path):
    xls = pd.ExcelFile(input_path)
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for sheet_name in xls.sheet_names:
            df = xls.parse(sheet_name)

            # Determine required columns based on sheet type
            if 'Objective' in sheet_name:
                required_columns = ['Question Category', 'Cognitive Skills', 'Question Source', 
                                   'Level of Difficulty', 'Marks', 'Answer Type']
            elif 'Subjective' in sheet_name:
                required_columns = ['Question Category', 'Cognitive Skills', 'Question Source', 
                                   'Level of Difficulty', 'Marks', 'Answer Type', 'Answer']
            elif 'Descriptive' in sheet_name:
                required_columns = ['Question Category', 'Cognitive Skills', 'Question Source', 
                                   'Level of Difficulty', 'Marks', 'Answer Type', 'Answer Content']
            else:
                continue

            # Initialize missing columns
            for col in required_columns:
                if col not in df.columns:
                    df[col] = pd.NA if col == 'Marks' else ""

            # Ensure Marks column is numeric
            if 'Marks' in df.columns:
                df['Marks'] = pd.to_numeric(df['Marks'], errors='coerce')
            
            # Process each question
            for index, row in df.iterrows():
                question_content = str(row['Question']) if 'Question' in row else ""

                if not question_content.strip():
                    continue

                try:
                    # Get GPT response
                    if 'Objective' in sheet_name:
                        details = get_objective_details(question_content)
                    elif 'Subjective' in sheet_name:
                        details = get_subjective_details(question_content)
                    elif 'Descriptive' in sheet_name:
                        details = get_descriptive_details(question_content)
                    
                    print(f"\nGPT Response for question {index + 1}:\n{details}")
                    
                    # Parse the response
                    parsed_data = {}
                    answer_content = []
                    in_answer_content = False
                    for line in details.split('\n'):
                        line = line.strip()
                        # Skip empty lines
                        if not line:
                            continue
                        # Detect Answer Content section with multiple possible headers
                        if (re.match(r'^(\d+\.\s*)?(Answer Content|Answer):', line, re.IGNORECASE) or
                            'solution will involve' in line.lower()):
                            in_answer_content = True
                            # Remove header part
                            line = re.sub(r'^(\d+\.\s*)?(Answer Content|Answer):\s*', '', line, flags=re.IGNORECASE).strip()
                            if line:
                                answer_content.append(line)
                            continue

                        if in_answer_content:
                            # Clean and keep answer content lines
                            clean_line = re.sub(r'^[\s\-•*]+', '', line)  # Remove leading bullets/dashes
                            if clean_line:
                                answer_content.append(clean_line)
                        else:
                            # Parse key-value pairs
                            if ': ' in line:
                                # Remove numbering prefix if present
                                line = re.sub(r'^\d+\.\s*', '', line)
                                key, value = line.split(': ', 1)
                                parsed_data[key.strip()] = value.strip()
                    
                    # Debug prints
                    print("Parsed Data:", parsed_data)
                    print("Answer Content:", answer_content)
                    
                    # Map to required columns
                    column_mapping = {
                        'Question Category': ['Question Category'],
                        'Cognitive Skills': ['Cognitive Skills'],
                        'Question Source': ['Question Source'],
                        'Level of Difficulty': ['Level of Difficulty'],
                        'Marks': ['Marks'],
                        'Answer Type': ['Answer Type'],
                        #'answer_type': ['Answer Type']  #  for subjective sheets
                    }
                    
                    details_list = []
                    for col in required_columns:
                        found = False
                        # Check all possible keys for this column
                        for key in column_mapping.get(col, [col]):
                            if key in parsed_data:
                                details_list.append(parsed_data[key])
                                found = True
                                break
                        
                        if not found and col in ['Answer Content', 'Answer']:
                            details_list.append('\n'.join(answer_content) if answer_content else "")
                        elif not found:
                            details_list.append(pd.NA if col == 'Marks' else "")
                    
                    print(f"Final Parsed Details: {details_list}")

                    # Update DataFrame
                    for i, col in enumerate(required_columns):
                        if i < len(details_list):
                            if col == 'Marks':
                                try:
                                    # Extract first number from marks field
                                    marks_value = re.search(r'\d+', str(details_list[i]))
                                    df.at[index, col] = float(marks_value.group()) if marks_value else pd.NA
                                except (ValueError, TypeError):
                                    df.at[index, col] = pd.NA
                            else:
                                # Store the full value, removing any surrounding quotes
                                value = str(details_list[i]).strip('"\'')
                                df.at[index, col] = value
                    
                except Exception as e:
                    print(f"Error processing question {index + 1}: {str(e)}")
                    continue

            # Save the sheet
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    print(f"\nSuccessfully processed and saved to {output_path}")

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'questionPaper' not in request.files or 'answerSheet' not in request.files:
        return jsonify({'error': 'Missing files'}), 400

    question_paper = request.files['questionPaper']
    answer_sheet = request.files['answerSheet']

    if question_paper.filename == '' or answer_sheet.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    print("Processing files with Mathpix...")
    question_txt_path = process_with_mathpix(question_paper)
    answer_txt_path = process_with_mathpix(answer_sheet)

    if not question_txt_path or not answer_txt_path:
        return jsonify({'error': 'Failed to process files with Mathpix'}), 500

    print("Generating intermediate Excel file...")
    intermediate_excel_path = "intermediate_output.xlsx"
    process_files_to_excel(question_txt_path, answer_txt_path, intermediate_excel_path)

    print("Processing Excel file with GPT...")
    final_excel_path = "final_output.xlsx"
    process_excel_file_with_gpt(intermediate_excel_path, final_excel_path)

    print("Sending final Excel file to the user...")

   # Return the final Excel file to the user
    print("Sending final Excel file to the user...")
    return send_file(
        final_excel_path,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='final_output.xlsx'
    )
@app.route("/", methods=["GET"])
def home():
    return " Backend is up and working!"

if __name__ == '__main__':
    app.run(debug=True, port=5000)


