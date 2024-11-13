class UserSettings:
    def __init__(self, data: list = None):
        # default values
        self.channel_id = None
        self.show_link = False
        self.screenshot = False
        self.delay = 0
        self.force_desc = False
        self.silent = 2
        self.private = False
        self.webhook = None
        self.message_level = 0
        self.take_delays = False
        if not data:
            return
        # data is a array of settings
        # convert "False" to False and "True" to True
        for i in range(len(data)):
            if data[i] == "False":
                data[i] = False
            elif data[i] == "True":
                data[i] = True
        # assign values
        self.channel_id = data[0] 
        self.show_link = data[1]
        self.screenshot = data[2]
        self.delay = data[3]
        self.force_desc = data[4]
        self.silent = data[5]
        self.private = data[6]
        self.webhook = data[7]
        self.message_level = data[8]
        self.take_delays = data[9]


