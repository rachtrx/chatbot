import pickle

def main():

    with open('text_clf_linearsvc_model.pk1', 'rb') as file:
        text_clf = pickle.load(file)
    
    
    
    while True:
        query = input("Type a Question: ")
        prediction = text_clf.predict([query])
        print(f"This is a question regarding {prediction}")

if __name__ == '__main__':
    main()