from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QMainWindow,QMessageBox
from tradeObjTestUi import Ui_MainWindow
import win32com.client
import win32com.client.dynamic
import datetime
import sys
import json

class EventHandler:
    def OnDataResponse(self,eventID,responseData):
        print(responseData)
        return
class MainAppcliaction(QMainWindow, Ui_MainWindow):
    
    def __init__(self,parent=None):
        QMainWindow.__init__(self,parent=parent)# 初始化QMainWindow
        self.setupUi(self)# 呼叫UI類別初始化
        # 
        self.ButtonLogin.clicked.connect(self.buttonLogin_Clicked)
        self.ButtonConnect.clicked.connect(self.buttonConnect_Clicked)
        self.ButtonDisconnect.clicked.connect(self.buttonDisconnect_Clicked)
        self.ButtonLogout.clicked.connect(self.buttonLogout_Clicked)

        self.ButtonSTKSend.clicked.connect(self.buttonSTKSendClick)
        self.ButtonSTKQueryPosition.clicked.connect(self.buttonStkQryPositionClicked)
        self.ButtonSTKQueryMatch.clicked.connect(self.buttonStkQryMatchClicked)
        self.ButtonSTKQueryOrder.clicked.connect(self.buttonStkQryOrderClicked)
       
        self.ButtonTFXSend.clicked.connect(self.buttonTFXSendClick)
        self.ButtonTFXQueryEQuity.clicked.connect(self.buttonTFXQryEQuityClicked)
        self.ButtonTFXQueryOI.clicked.connect(self.buttonTFXQryOIClicked)
        self.ButtonTFXQueryOrder.clicked.connect(self.buttonTFXQryOrderClicked)
        self.ButtonTFXQueryMatch.clicked.connect(self.buttonTFXQryMatchClicked)

        self.ButtonClearResult.clicked.connect(self.buttonClearResultClicked)
        self.ButtonClearMSN.clicked.connect(self.buttonClearMSNClicked)
        
    def Init(self):
        # TODO config reader
        self.InitTradeapp()  
        jsonFile = open('appsetting.json')
        f=jsonFile.read()
        a=json.loads(f)
        (Ret, self.Errcode, self.Errmsg)=self.tradeApp.Init(a["TradeDas"])
        self.tradeApp.SetEchoType(1, 1)
        self.tradeApp.SetLotSizeData("0050=1000|0028=1000")
        today = datetime.date.today()
        self.TextboxOrderDate.setText(today.strftime('%Y%m%d'))
        self.SetSTK_ComboBoxBS()
        self.SetSTK_ComboBoxOT()
        self.SetSTK_ComboBoxCond()
        self.SetSTK_ComboBoxPT()
        self.SetSTK_ComboBoxTT()
        self.SetTFX_ComboBoxTT()
        self.StkConn=0
        self.FutConn=0
        self.HKConn=0
        self.UpdateConnectStatus()
    def InitTradeapp(self):
        self.tradeApp = win32com.client.DispatchWithEvents("DJTRADEOBJLibCTS.TradeApp",EventHandler)
        self.tradeApp.OnDataResponse=self.OnDataResponse

    def OnDataResponse(self,eventID,responseData):
       match eventID:
            case 1:
                #setconnectstatus
                return
            case 10:
                self.textResult.setText(responseData)
                return
            case 100:
                if self.textMSN.toPlainText():
                   self.textMSN.setText(self.textMSN.toPlainText()+"\r\n")
                self.textMSN.setText(self.textMSN.toPlainText()+responseData)
            case 101| 102|103:
                self.textResult.setText(responseData.replace(">", ">\r\n"))

    def SetConnectStatus(self,Data):
        Conns= Data.split(",")
        if len(Conns) >=2:
            match Conns[0]:
                case 1:
                    self.StkConn=Conns[1]
                case 2:
                    self.FutConn=Conns[1]
                case 3:
                    self.HKConn=Conns[1]
            self.UpdateConnectStatus()

    def UpdateConnectStatus(self):
        self.labelSTKConnect.setText(f"證卷:{'' if self.StkConn == 0 else '已連線'}")
        self.labelTFXConnect.setText(f"期權:{'' if self.FutConn == 0 else '已連線'}")
        self.labelHKAConnect.setText(f"複委託:{'' if self.HKConn == 0 else '已連線'}")

    def Fini(self):
        try:
            self.tradeApp.Fini()
        except Exception as ex:
             QMessageBox.critical(self,"",repr(ex))
             sys.exit()


    def showEvent(self,event): #視窗開啟事件
        try:
            self.Init()
            self.textboxUID.setText("16795856")
            self.textboxPassword.setText("1111")
        except Exception as ex:
             QMessageBox.critical(self,"",repr(ex))
             sys.exit()


    def closeEvent(self,event): # 視窗關閉事件
        result= QMessageBox.question(self,
            "關閉程式","Are you sure want to quit?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if result==QMessageBox.Yes:
            self.Fini()
            event.accept()
        else:
            event.ignore()

    def SetSTK_ComboBoxBS(self):
        self.ComboboxSTKBS.addItem("買進",1)
        self.ComboboxSTKBS.addItem("賣出",2)
        self.ComboboxSTKBS.setCurrentIndex(0)

    def SetSTK_ComboBoxOT(self):
        self.ComboboxSTKOT.addItem("現股",0)
        self.ComboboxSTKOT.addItem("融資",1)
        self.ComboboxSTKOT.addItem("融券",2)
        self.ComboboxSTKOT.addItem("現沖先賣",16)
        self.ComboboxSTKOT.setCurrentIndex(0)
    # TODO MAPPING VALUE
            #     string[] arshow = { "現股", "融資", "融券", "現沖先賣" };
            #     int[] arItemValue = { 0, 1, 2, 16 };

    def SetSTK_ComboBoxTT(self):
        self.ComboboxSTKTT.addItem("普通",0)
        self.ComboboxSTKTT.addItem("盤後零股",1)
        self.ComboboxSTKTT.addItem("盤後",2)
        self.ComboboxSTKTT.addItem("興櫃",5)
        self.ComboboxSTKTT.setCurrentIndex(0)
        #     string[] arshow = { "普通", "盤後零股", "盤後", "興櫃", "盤中零股"};
        #     int[] arItemValue = { 0, 1, 2, 5, 7 };

    def SetSTK_ComboBoxPT(self):
        self.ComboboxSTKPT.addItem("限價",0)
        self.ComboboxSTKPT.addItem("漲停",1)
        self.ComboboxSTKPT.addItem("跌停",2)
        self.ComboboxSTKPT.addItem("平盤",3)
        self.ComboboxSTKPT.addItem("市價",4)
        self.ComboboxSTKPT.setCurrentIndex(0)


    def SetSTK_ComboBoxCond(self):
        self.ComboboxSTKCond.addItem("ROD",0)
        self.ComboboxSTKCond.addItem("IOC",1)
        self.ComboboxSTKCond.addItem("FOK",2)
        self.ComboboxSTKCond.setCurrentIndex(0)    

    def SetTFX_ComboBoxTT(self):
        self.ComboboxTFXTT.addItem("期貨",0)
        self.ComboboxTFXTT.addItem("權證",1)

    def  SetAccountList(self):
        self.listAccount.clear()
        self.ComboboxSTKAccount.clear()
        self.ComboboxTFXAccount.clear()
        nCount=self.tradeApp.GetAccountCount()
        for i in range(0,nCount):
            AccountData=self.tradeApp.GetAccount(i)
            AccountData=AccountData.strip('<>')
            self.listAccount.addItem(AccountData)#TODO AFTER LOGIN
            Field=AccountData.split("|")
            if len(Field)<4:
                continue
            AccountId=Field[0].split("=")
            AccountName=Field[1].split("=")
            AccountUID=Field[2].split("=")
            AccountType=Field[3].split("=")
            AccountItem=AccountName[1] + "|" + AccountId[1]
            match AccountType[1]:
                case '1':
                    self.ComboboxSTKAccount.addItem(AccountItem)
                case '2':
                    self.ComboboxTFXAccount.addItem(AccountItem)
                #case '3':
                    #HKAccount.Items.Add(arAccName[1] + "|" + arAccID[1]);

                #  ALLAccount.Items.Add(arAccName[1] + "|" + arAccID[1]);
            if self.ComboboxSTKAccount.count()>0:
                self.ComboboxSTKAccount.setCurrentIndex(0)
            if self.ComboboxTFXAccount.count()>0:
                self.ComboboxTFXAccount.setCurrentIndex(0)
            # if self.ComboboxHKAccount.count()>0:
            #     self.ComboboxHKAccount.setCurrentIndex(0)
            # if self.ComboboxALLAccount.count()>0:
            #     self.ComboboxALLAccount.setCurrentIndex(0)


#  private int GetCond() 由 currentData()取代

    def GetAccountString(self,Type):
        match Type:
            case "STK":
                Args= self.ComboboxSTKAccount.currentText().split('|')
                return  Args[1] if len(Args)>1 else ""
            case "TFX":
                Args= self.ComboboxTFXAccount.currentText().split('|')
                return  Args[1] if len(Args)>1 else ""
            # case "HK":
            #     Args= self.ComboboxHKAccount.currentText().split('|')
            #     return  Args[1] if len(Args)>1 else ""
            # case "ALL":
            #     Args= self.ComboboxALLAccount.currentText().split('|')
            #     return  Args[1] if len(Args)>1 else ""
        return ""


    def buttonLogin_Clicked(self):
        errCode=0
        sErrMsg = ""
        try:
            (result,ErrCode,ErrMsg)= self.tradeApp.Login(self.textboxUID.text(), self.textboxPassword.text())
            if result == 1:
                self.SetAccountList()
                if self.ComboboxSTKAccount.count()>0:
                    self.ButtonSTKSend.setEnabled(True)
                    self.ButtonSTKQueryMatch.setEnabled(True)
                    self.ButtonSTKQueryOrder.setEnabled(True)
                    self.ButtonSTKQueryPosition.setEnabled(True)
                    
                if self.ComboboxTFXAccount.count()>0:
                    self.ButtonTFXSend.setEnabled(True)
                    self.ButtonTFXQueryOI.setEnabled(True)
                    self.ButtonTFXQueryMatch.setEnabled(True)
                    self.ButtonTFXQueryOrder.setEnabled(True)                   
                    self.ButtonTFXQueryEQuity.setEnabled(True)
                # if self.ComboboxHKAccount.count()>0:
                #     self.ButtonHKSend.setEnabled(True)
                #     self.ButtonHKQueryMatch.setEnabled(True)
                #     self.ButtonHKQueryOrder.setEnabled(True)
                #     self.ButtonHKQueryPosition.setEnabled(True)
                # if self.ComboboxALLAccount.count()>0:
                #     self.ButtonMixQuery.setEnabled(True)
                QMessageBox.about(self,"","登入成功")  
                self.ButtonConnect.setEnabled(True) 
                self.ButtonLogout.setEnabled(True) 
                self.ButtonLogin.setEnabled(False) 
            else:
                QMessageBox.critical(self,"",f"登入失敗:{ErrMsg}")

        except Exception as ex:
            QMessageBox.critical(self,"",repr(ex))
    def buttonConnect_Clicked(self):
        if self.tradeApp.Connect() != 0:
            self.ButtonConnect.setEnabled(False)
            self.ButtonDisconnect.setEnabled(True)
        else:
            QMessageBox.critical(self,"","無法連線")

    def buttonDisconnect_Clicked(self):
        self.tradeApp.Disconnect()
        self.ButtonConnect.setEnabled(True)
        self.ButtonDisconnect.setEnabled(False)
        self.StkConn=0
        self.FutConn=0
        self.HKConn=0
        self.UpdateConnectStatus()
    
    def buttonLogout_Clicked(self):
        self.ButtonLogin.setEnabled(True)
        self.ButtonLogout.setEnabled(False)
        self.ButtonConnect.setEnabled(False)
        self.ButtonDisconnect.setEnabled(False)
        
        self.tradeApp.Logout(self.textboxUID.text())
        self.listAccount.clear()
        self.ComboboxSTKAccount.clear()
        self.ComboboxTFXAccount.clear()

        # self.ComboboxHKAccount.clear()
        # self.ComboboxALLAccount.clear()
        self.ButtonSTKSend.setEnabled(False)
        self.ButtonSTKQueryMatch.setEnabled(False)
        self.ButtonSTKQueryOrder.setEnabled(False)
        self.ButtonSTKQueryPosition.setEnabled(False)
                    
        self.ButtonTFXSend.setEnabled(False)
        self.ButtonTFXQueryOI.setEnabled(False)
        self.ButtonTFXQueryMatch.setEnabled(False)
        self.ButtonTFXQueryOrder.setEnabled(False)                   
        self.ButtonTFXQueryEQuity.setEnabled(False)

        #self.ButtonHKSend.setEnabled(False)
        #self.ButtonHKQueryMatch.setEnabled(False)
        #self.ButtonHKQueryOrder.setEnabled(False)
        #self.ButtonHKQueryPosition.setEnabled(False)
        #self.ButtonMixQuery.setEnabled(False)  







            # private void SetHK_CBTT()
            # {
            #     HKTT.Items.Clear();

            #     string[] arshow = { "港股", "美股" };
            #     int[] arItemValue = { 0, 2 };

            #     List<ComboboxItem> datalist = new List<ComboboxItem>();
            #     for (int i = 0; i < arshow.Length; ++i)
            #     {
            #         ComboboxItem item = new ComboboxItem();
            #         item.Text = arshow[i];
            #         item.Value = arItemValue[i];
            #         datalist.Add(item);
            #     }

            #     HKTT.DisplayMember = "Text";　  // ComboBox 將會顯示 Student 物件的 Tel 資訊。
            #     HKTT.ValueMember = "Value";
            #     HKTT.DataSource = datalist;

            #     HKTT.SelectedIndex = 0;
            # }


        




        # private void btnClearResult_Click(object sender, EventArgs e)
        # {
        #     txtResult.Text = "";
        # }

        # private void btnClearMSN_Click(object sender, EventArgs e)
        # {
        #     txtMSN.Text = "";
        # }

                

       

    # region STOCK
    
    # STK RADIO
    def buttonSTKSendClick(self):
        if self.RadioSTKNewOrder.isChecked():
            self.btnStkNewOrder()
        elif self.RadioSTKModifyOrder.isChecked():
            self.btnStkModifyOrder()
        elif self.RadioSTKCancelOrder.isChecked():
            self.btnStkCancelOrder()
        elif self.RadioSTKModifyPrice.isChecked():
            self.btnStkModifyPrice()
            
    def btnStkNewOrder(self):
        AccountID=self.GetAccountString("STK")
        TT= self.ComboboxSTKTT.currentData()
        OT= self.ComboboxSTKOT.currentData()
        BS=self.ComboboxSTKBS.currentData()
        PT=self.ComboboxSTKPT.currentData()
        stockID=self.TextboxSTKID.text()
        Qty=self.TextboxSTKQty.text()
        if (not try_parse_int(Qty)):# or int(Qty)==0:
            QMessageBox.about(self,"","請輸入數量")
            return
        Price=self.TextboxSTKPrice.text()

        if (not try_parse_float(Price)) or PT !=0:
            Price="0"
        Broker=""
        PayType=0
        Cond=self.ComboboxSTKCond.currentData()
        tradeDate=self.TextboxOrderDate.text()
        result= self.tradeApp.Stock_NewOrder(AccountID,tradeDate,TT,OT,BS,stockID,Qty,PT,Price,Broker,PayType,Cond)
        if result:
            QMessageBox.about(self,"",result) 

    def btnStkModifyOrder(self):
        AccountID=self.GetAccountString("STK")
        TT= self.ComboboxSTKTT.currentData()
        OT= self.ComboboxSTKOT.currentData()
        OID=self.TextboxSTKOID.text()
        stockID=self.TextboxSTKID.text()
        OrderNumber=self.TextboxSTKOrderNumber.text()
        Price=self.TextboxSTKPrice.text() # 改量 不檢查價格
        BS=1
        Qty=self.TextboxSTKQty.text()
        if (not try_parse_int(Qty)) :
            QMessageBox.about(self,"","請輸入數量")
            return
        Qty=int(Qty)
        # PT=self.ComboboxSTKPT.currentData()
        QCurrent=self.TextboxSTKQCurrent.text()
        if (not try_parse_int(QCurrent)) :
            QMessageBox.about(self,"","請輸入數量 (nQCurrent)")
            return
        QCurrent=int(QCurrent)

        QMatch=self.TextboxSTKQMatch.text()
        if (not try_parse_int(QMatch)) :
            QMatch=0
        else:
            QMatch=int(QMatch)

        PreOrder=1 if self.CheckSTKPreOrder.isChecked() else 0

        # Cond=self.ComboboxSTKCond.currentData()
        tradeDate=self.TextboxOrderDate.text()
        result= self.tradeApp.Stock_ModifyOrder(AccountID,tradeDate,TT,OT,OID,OrderNumber,stockID,BS,Qty,QCurrent,QMatch,PreOrder,0,Price,0,0)
        if result:
            QMessageBox.about(self,"",result) 

    def btnStkCancelOrder(self):
        AccountID=self.GetAccountString("STK")
        TT= 0
        OT= 0
        OID=self.TextboxSTKOID.text()
        stockID=self.TextboxSTKID.text()
        OrderNumber=self.TextboxSTKOrderNumber.text()
        BS=1
        Qty=self.TextboxSTKQty.text()
        if (not try_parse_int(Qty)) :
            QMessageBox.about(self,"","請輸入數量")
            return
        Qty=int(self.TextboxSTKQty.text())


        QCurrent=self.TextboxSTKQCurrent.text()
        if (not try_parse_int(QCurrent)) :
            QMessageBox.about(self,"","請輸入數量(QCurrent)")
            return
        QCurrent= int(self.TextboxSTKQCurrent.text())
        

        QMatch=self.TextboxSTKQMatch.text()
        if (not try_parse_int(QMatch)) :
            QMatch=0
        else:
            QMatch=int(self.TextboxSTKQMatch.text())
        PreOrder=1 if self.CheckSTKPreOrder.isChecked() else 0

        tradeDate=self.TextboxOrderDate.text()
        PT=self.ComboboxSTKPT.currentData()
        Price=self.TextboxSTKPrice.text()
        if PT !=0:
            Price="0"
        Cond=self.ComboboxSTKCond.currentData()
        result= self.tradeApp.Stock_CancelOrder(AccountID,tradeDate,TT,OT,OID,OrderNumber,stockID,BS,Qty,QCurrent,QMatch,PreOrder,Price,PT,Cond)
        if result:
            QMessageBox.about(self,"",result) 
            
    def btnStkModifyPrice(self):
        AccountID=self.GetAccountString("STK")
        TT= 0
        OT= 0
        OID=self.TextboxSTKOID.text()
        stockID=self.TextboxSTKID.text()
        OrderNumber=self.TextboxSTKOrderNumber.text()
        Price=self.TextboxSTKPrice.text() if self.ComboboxSTKPT.currentData()==0 else "0"
        BS=1
        Qty=0 #改價 量不動
        QCurrent=self.TextboxSTKQCurrent.text()
        if (not try_parse_int(QCurrent)) :
            QMessageBox.about(self,"","請輸入數量 (nQCurrent)")
            return
        QCurrent=int(QCurrent)

        QMatch=self.TextboxSTKQMatch.text()
        if (not try_parse_int(QMatch)) :
            QMatch=0        
        QMatch=int(QMatch)
        
        PreOrder=1 if self.CheckSTKPreOrder.isChecked() else 0
        Cond=self.ComboboxSTKCond.currentData()
        PT=self.ComboboxSTKPT.currentData()
        

        
        tradeDate=self.TextboxOrderDate.text()
        result= self.tradeApp.Stock_ModifyOrder(AccountID,tradeDate,TT,OT,OID,OrderNumber,stockID,BS,Qty,QCurrent,QMatch,PreOrder,2,Price,PT,0)
        if result:
            QMessageBox.about(self,"",result) 


    def buttonStkQryOrderClicked(self):
        accountID = self.GetAccountString("STK")
        forceQuery= 1 if self.CheckSTKForceQuery.isChecked() else 0
        result = self.tradeApp.Stock_QueryOrder(accountID, forceQuery)
        
        if result:
            QMessageBox.about(self,"",result) 

        
    def buttonStkQryMatchClicked(self):
        accountID = self.GetAccountString("STK")
        forceQuery= 1 if self.CheckSTKForceQuery.isChecked() else 0
        result = self.tradeApp.Stock_QueryMatch(accountID, forceQuery)
        
        if result:
            QMessageBox.about(self,"",result) 



    def buttonStkQryPositionClicked(self):
        accountID = self.GetAccountString("STK")
        forceQuery= 1 if self.CheckSTKForceQuery.isChecked() else 0
        tradeDate=self.TextboxOrderDate.text()
        result = self.tradeApp.Stock_QueryPosition(accountID, tradeDate, forceQuery)
        
        if result:
            QMessageBox.about(self,"",result) 



    # region TFX


    def buttonTFXSendClick(self):

        if self.RadioTFXNewOrder.isChecked():
            self.btnTfxNewOrder()
        elif self.RadioTFXModifyOrder.isChecked():
            self.btnTfxModifyOrder()
        elif self.RadioTFXCancelOrder.isChecked():
            self.btnTfxCancelOrder()



    def btnTfxNewOrder(self):
        AccountID=self.GetAccountString("TFX")
        TT= self.ComboboxTFXTT.currentData() # 期權商品類型 (0:期貨, 1:選擇權, 2:選擇權複式, 3:期貨複式)
        if TT==2 or TT==3:
            TT=0
        TradeID1 = self.TextboxTFXTradeID.text()
        BS1=1
        PT=0
        Price=self.TextboxSTKPrice.text()
        if len(Price)==0:
            Price="0"
            PT=4
        Qty=self.TextboxSTKQty.text()
        if (not try_parse_int(Qty)):
            QMessageBox.about(self,"","請輸入數量")
            return
        Qty=int(Qty)

        
        Offset=0
        Cond=0
        TradeID2=""
        BS2=0
        PreOrder=1 if self.CheckTFXPreOrder.isChecked() else 0
        tradeDate=self.TextboxOrderDate.text()        

        result= self.tradeApp.FutOpt_NewOrder(AccountID,tradeDate,TT,TradeID1,BS1,PT,Price,Qty,Offset,Cond,TradeID2,BS2,PreOrder)
        if result:
            QMessageBox.about(self,"",result) 

    def btnTfxModifyOrder(self):
        AccountID=self.GetAccountString("TFX")
        Type=0
        OID=self.TextboxTFXOID.text()
        OrderNo=self.TextboxTFXOrderNo.text()
        Qty=self.TextboxTFXQty.text()
        if (not try_parse_int(Qty)):
            QMessageBox.about(self,"","請輸入數量")
            return
        Qty=int(Qty)

        TT= self.ComboboxTFXTT.currentData() # 期權商品類型 (0:期貨, 1:選擇權, 2:選擇權複式, 3:期貨複式)
        if TT==2 or TT==3:
            TT=0

        QCurrent=self.TextboxTFXQCurrent.text()
        if (not try_parse_int(QCurrent)) :
            QMessageBox.about(self,"","請輸入數量 (nQCurrent)")
            return
        QCurrent=int(QCurrent)


        QMatch=self.TextboxTFXQMatch.text()
        if (not try_parse_int(QMatch)) :
            QMatch=0   
        QMatch=int(QMatch)

        PreOrder=1 if self.CheckTFXPreOrder.isChecked() else 0
        NewPT=1
        NewPrice="0"
        NewCond=0

    
        TradeID1 = self.TextboxTFXTradeID.text()
        TradeID2=""
        BS1=1
        PT=0
        tradeDate=self.TextboxOrderDate.text()
   

        result= self.tradeApp.FutOpt_ModifyOrder(AccountID,Type,tradeDate,OID,OrderNo,Qty,TT,QCurrent,QMatch,PreOrder,NewPT,NewPrice,NewCond,TradeID1,TradeID2)
        if result:
            QMessageBox.about(self,"",result) 


    def btnTfxCancelOrder(self):
        AccountID=self.GetAccountString("TFX")
        OID=self.TextboxTFXOID.text()
        OrderNo=self.TextboxTFXOrderNo.text()
        Qty=self.TextboxTFXQty.text()
        if (not try_parse_int(Qty)):
            QMessageBox.about(self,"","請輸入數量")
            return
        Qty=int(Qty)

        TT= self.ComboboxTFXTT.currentData() # 期權商品類型 (0:期貨, 1:選擇權, 2:選擇權複式, 3:期貨複式)
        if TT==2 or TT==3:
            TT=0

        QCurrent=self.TextboxTFXQCurrent.text()
        if (not try_parse_int(QCurrent)) :
            QMessageBox.about(self,"","請輸入數量 (nQCurrent)")
            return
        QCurrent=int(QCurrent)
        
        QMatch=self.TextboxTFXQMatch.text()
        if (not try_parse_int(QMatch)) :
            QMatch=0  
        QMatch=int(QMatch) 

        PreOrder=1 if self.CheckTFXPreOrder.isChecked() else 0
        TradeID1 = self.TextboxTFXTradeID.text()
        TradeID2=""        

        tradeDate=self.TextboxOrderDate.text()
   

        result= self.tradeApp.FutOpt_CancelOrder(AccountID,tradeDate,OID,OrderNo,Qty,TT,QCurrent,QMatch,PreOrder,TradeID1,TradeID2)
        if result:
            QMessageBox.about(self,"",result) 


    def buttonTFXQryOrderClicked(self):
        accountID = self.GetAccountString("TFX")
        nTT = 0 #期權商品類型 (0:期貨, 1:選擇權, 2:選擇權複式, 3:期貨複式)
        forceQuery= 1 if self.CheckSTKForceQuery.isChecked() else 0
        result = self.tradeApp.FutOpt_QueryOrder(accountID, nTT, forceQuery)
        
        if result:
            QMessageBox.about(self,"",result) 

    def buttonTFXQryMatchClicked(self):
        accountID = self.GetAccountString("TFX")
        forceQuery= 1 if self.CheckSTKForceQuery.isChecked() else 0
        result = self.tradeApp.FutOpt_QueryMatch(accountID, forceQuery)
        
        if result:
            QMessageBox.about(self,"",result) 

    def buttonTFXQryOIClicked(self):
        accountID = self.GetAccountString("TFX")
        forceQuery= 1 if self.CheckSTKForceQuery.isChecked() else 0
        tradeDate=self.TextboxOrderDate.text()
        result = self.tradeApp.FutOpt_QueryOrder(accountID,tradeDate, forceQuery)
        
        if result:
            QMessageBox.about(self,"",result) 
    
    def buttonTFXQryEQuityClicked(self):
        accountID = self.GetAccountString("TFX")
        forceQuery= 1 if self.CheckSTKForceQuery.isChecked() else 0
        result = self.tradeApp.FutOpt_QueryEquity(accountID,"")
        
        if result:
            QMessageBox.about(self,"",result) 

    def buttonClearResultClicked(self):
        self.textResult.setPlainText("")
    def buttonClearMSNClicked(self):
        self.textMSN.setPlainText("")
def try_parse_int(value):
    try:
        result = int(value)
        return True
    except ValueError:
        return False
def try_parse_float(value):

    try:
        result = float(value)
        return True
    except ValueError:
        return False