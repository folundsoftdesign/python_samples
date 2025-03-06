use('sample');

db.createUser({
    user: "sample",
    pwd: "samplester",
    roles: [
        {
            role: "dbAdmin",
            db: "sample"
        }
    ] 
});


