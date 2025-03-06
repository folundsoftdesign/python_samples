use('fraud');

db.createUser({
    user: "fraud",
    pwd: "fraudster",
    roles: [
        {
            role: "dbAdmin",
            db: "fraud"
        }
    ] 
});


